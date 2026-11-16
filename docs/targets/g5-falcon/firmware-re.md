# G5 (FALCON) firmware reverse engineering — foundation for the feature patches

Target: `M-C5500GGZA-1008.3` (the unit's version). The executable records are **byte-identical** to the images
analysed in `github:c8dhjp4tyv-bit/odyssey-g5-firmware-research` (only EDID names and the embedded version differ,
record 6), so that project's SPARC function catalog maps **directly** onto our image at the same offsets. The
firmware also carries **embedded debug-symbol strings**, so handlers can be named reliably. Confidence per ADR-0001.

## Package (NVTSC_IMG, 10 records)

Main SPARC application is **record 5** (flash target `0x108000`, container file `0x2DCE0..0x21DCE0`). Relocated
code/tables live at file `0x12E000..0x21DCE0`. Two address regions, each a constant file↔VA shift:

| Region | VA start | File start | Relation |
|---|---|---|---|
| SPARC code | `0x100000` | `0x12E000` | **file = VA + 0x2E000** |
| SPARC data | `0x1F0000` | `0x21DD00` | **file = VA + 0x2DD00** |

Verified locally: the canonical firmware string "M-C5500GGZA-1008.3" is at file `0x273358` (data VA `0x245658`),
and the MGA-supported byte is `0x00` at file `0x2D2776` (data VA `0x2A4A76`).

## DDC/CI handlers (confirmed on our image)

Located by their embedded debug-symbol strings and disassembled with capstone (SPARC-V8, big-endian):

| Symbol | VA | File offset | Role |
|---|---|---|---|
| `SecLibCommon_DdcCmdGetVcp` | `0x1882AC` | `0x1B62AC` | **Get VCP handler** |
| `SecLibCommon_DddCmdSetVcp` | `0x1869BC` | `0x1B49BC` | **Set VCP handler** |
| `SecLibCommon_DddCmdAdjustOSDFunction` | `0x186F4C` | `0x1B4F4C` | OSD-apply after Set |
| `__setVcpOffTimer` | `0x185BAC` | `0x1B3BAC` | off-timer Set path |

The symbol strings are at data VA `0x23B5E8` (GetVcp) / `0x23B5A0` (SetVcp); the DDC capability strings are at data
VA `0x23B230`+ (file `0x268F30`+, four model variants, `model(LEMON23...)`).

### DDC command dispatcher (the LC34-style hook point)

`sub_103DBC` (VA `0x103DBC`, file `0x131DBC`, size `0x81C`) is the DDC/CI command dispatcher: it calls
`DdcCmdGetVcp` (from `0x103EBC`) and `DddCmdSetVcp` (from `0x104148`/`0x104170`). It parses the packet and routes by
opcode — the analogue of the sibling ASUS `FUN_00085d0c`. **Intercepting a chosen VCP code here** (before the normal
Get/Set path) is the clean way to add memory read/write, exactly as the LC34 hook does, and sidesteps the sparse
jump table below (which is sized to the stock supported codes, not a full 255-entry array, so new codes cannot be
added by extending it).

### Get VCP dispatch (the handler internals)

`SecLibCommon_DdcCmdGetVcp(%i0 = vcp code, %i1 = 4-byte reply buffer MH/ML/CH/CL)` — same shape as the LC34 handler:

```sparc
stb   %g0,[%i1] ; %i1+1 ; +2 ; +3      ; clear the 4 reply bytes
...                                     ; bail if DDC/CI disabled (cfg byte)
and   %i0, 0xff, %l0                    ; l0 = vcp code
cmp   %l0, 0xfe ; bgu,a ...             ; code > 0xFE -> unsupported
sll   %l0, 2, %o7                       ; o7 = code * 4
sethi 0x613, %g1 ; or %g1,0x32c,%l0     ; l0 = 0x184F2C  (jump-table base VA)
ld    [%l0+%o7], %o1 ; jmp %o1          ; jump to table[code]
```

Jump table base: **VA `0x184F2C`, file `0x1B2F2C`**. Low codes index valid handler pointers (e.g. `0x10/0x12 ->
0x188620`, a generic get-value handler shared by ~27 codes; `0x13 -> 0x188AE4`, `0x14 -> 0x188A74`). **Open:** the
flat `code*4` indexing holds only for low codes; the vendor range (`0xE0..0xFE`, incl. the `FE`/`F1` service escapes
seen on the NT68552 sibling) is reached by a separate path — to be disassembled to pick a free code and confirm the
exact table extent.

## Plan for the memory-read/write feature (step 1 toward DDC flashing)

1. Finish the Get/Set VCP dispatch map: exact jump-table extent, the vendor-range path, and a genuinely free code.
2. Find a code cave (unused padding in the code region) for the hook routines.
3. Add a Get-VCP "read 4 bytes at an address" + Set-VCP "set address / write byte" pair (LC34 `0xF0..0xF4` analogue),
   hooking the jump-table entry/entries to cave routines written in SPARC and assembled into the image.
4. Build with `mfw.novatek` (restamp + recompute sum16), flash from USB (user go-ahead), test over DDC.

These memory primitives are also the building blocks for the eventual DDC→flash writer (the "flash over HDMI" goal),
which targets the inactive A/B bank and validates before switching.

### Dispatcher internals and the exact hook point (confirmed by disassembly)

`sub_103DBC` reads the DDC packet to a stack buffer, then:

```sparc
; XOR checksum must be 0x6E (same convention as the LC34)
and  %l0, 0xff, %o5 ; cmp %o5, 0x6e ; bne 0x1045d0   ; bad checksum -> drop
ldub [%fp-0x2e], %l0                                 ; %l0 = opcode
cmp %l0, 0xc2 / 0xcb / 0x03 / 0x07 / 0x01 ...         ; opcode compare chain
; opcode 0x01 = Get VCP:
ldub [%fp-0x2d], %o2                                 ; %o2 = VCP code
... build reply header (0x6E 0x88 0x02 ...) on stack ...
and  %o2, 0xff, %o0                                  ; %o0 = VCP code
add  %fp, -0x60, %o1                                 ; %o1 = reply buffer (MH/ML/CH/CL at +0x?）
0x103EBC: call 0x1882ac (DdcCmdGetVcp)               ; <-- HOOK SITE (Get)
         mov %l3, %o2
; opcode 0x03 = Set VCP dispatches at 0x1040e8 -> DddCmdSetVcp (0x1869BC)
```

**Hook plan (LC34-style), confirmed feasible:**

| What | Where |
|---|---|
| Get hook site | redirect `call` at VA `0x103EBC` (file `0x131EBC`) → our Get hook; `%o0`=code, `%o1`=reply buf |
| Set hook site | the opcode-0x03 path near VA `0x1040E8` → our Set hook; intercept before `DddCmdSetVcp` |
| Hook code | reclaimed dead code (PDIC stub at VA `0x1E45D4`+) |
| New VCP codes | pick free codes (LC34 used `0xF0` addr-hi, `0xF1` addr-lo, `0xF2` read4, `0xF4` write1); unsupported stock codes fall through to `DdcCmdGetVcp`, so interception adds them cleanly |
| Scratch state | a few RAM/settings bytes to hold the current address (LC34 used its RAM block) — to be located |

The hook routine: if `%o0`/code == our read code, read 4 bytes at the current address and store to `[%o1..+3]`, return 1
(supported); else branch to the real `DdcCmdGetVcp` (`0x1882AC`). Set side mirrors it for address/write.

## Code-cave strategy (confirmed: the code is packed)

The SPARC code region (file `0x12E000..0x21DCE0`) has **no zero/nop padding runs ≥ 64 bytes** — unlike the LC34's
MStar cave, there is no free padding to inject into. The hook code must therefore **reclaim dead code**: uncalled
stubs the sibling RE flagged (PDIC/TCON/FPGA update stubs with no reachable callers). Confirmed present on our image:

| Candidate | VA | File | Size | Callers | Note |
|---|---|---|---|---|---|
| PDIC "not implemented" stub | `0x1E45D4` | `0x2125D4` | `0x90` (144 B) | **0** | confirmed dead; enough for the Get+Set hook |
| adjacent stub | `0x1E4510` | `0x212510` | `0x40` (64 B) | **0** | also dead; extra room if needed |

Confirmed in `main_direct_call_edges.csv`: no edge targets `0x1E45D4`. 144 bytes is ample for a memory read/write hook.

### Remaining before writing the hook

- **Scratch RAM** for the current address (LC34 used its RAM block): locate a few unused runtime bytes
  (`0xA80xxxxx` globals or spare settings bytes). Next step.
- **SPARC ABI for the hook**: the hook is entered at the Get call site with `%o0`=code, `%o1`=reply buf; it may use
  `%o2..%o5`/`%g1..%g4` freely (caller-saved), must preserve the caller's `%i*`/`%l*`, and ends by either returning a
  value in `%o0` or branching to the real handler. No `save` needed if it stays in the caller's window.
