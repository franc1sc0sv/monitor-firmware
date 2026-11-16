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

### Finalized hook design (proof patch first — no scratch RAM needed)

The DDC state block at `0xA803B0xx` is densely used, so guessing spare RAM there is risky. The **first** patch is a
minimal proof that needs no scratch: a new Get-VCP code `0xF2` that returns a magic value, validating the whole hook
pipeline on hardware before the real memory addressing is added.

Call-site redirect at VA `0x103EBC` (file `0x131EBC`): change `call 0x1882AC` → `call CAVE` (`0x1E45D4`). The delay
slot `mov %l3, %o2` still runs, so the original args survive. At CAVE: `%o7 = 0x103EBC` (from `call`), `%o0 = code`,
`%o1 = reply buf`.

```sparc
CAVE (0x1E45D4):           ; proof: code 0xF2 -> magic
  cmp  %o0, 0xF2
  bne  0x1882AC            ; not ours: BRANCH (not call) to real GetVcp, %o7 preserved
   nop                     ; delay slot
  mov  0xAD,%g1 ; stb %g1,[%o1]     ; MH
  mov  0xDE,%g1 ; stb %g1,[%o1+1]   ; ML
  mov  0xBE,%g1 ; stb %g1,[%o1+2]   ; CH
  mov  0xEF,%g1 ; stb %g1,[%o1+3]   ; CL
  retl                     ; return to %o7+8 = 0x103EC4 (dispatcher checks %o0)
   mov  1,%o0              ; delay slot: return "supported"
```

Why it is correct: the dispatcher's `call` sets `%o7 = 0x103EBC`; both `retl` (ours) and `DdcCmdGetVcp`'s `ret`
return to `%o7+8 = 0x103EC4`, exactly where the stock flow resumes (`andcc %o0,0xff` — the supported check). So a
read of VCP `0xF2` over DDC should return `AD DE BE EF`; every other code behaves bit-for-bit as stock.

**VALIDATED ON HARDWARE 2026-11-15.** Built `M-C5500GGZA-1010.0[C349]` (proof_hook.py), flashed from USB. Over
DDC/CI on the AMD HDMI link, Get VCP `0xF2` returns the magic bytes and `0x10/0x12/0x60` are unchanged. This proves
custom injected code runs on the G5 and answers over HDMI — the foundation for the memory read/write VCPs. The four
reply bytes come back as MH:ML:CH:CL = `EF DE BE AD`, i.e. the buffer at `%o1` maps to the reply fields in the order
`[+3][+1][+2][+0]` (to pin down exactly from a stock handler's buffer-fill before the memory-read feature).

### Set VCP path (for F0/F1 address and F4 write)

In `sub_103DBC`, the Set VCP packet is on the stack: `[%fp-0x2e]`=opcode(03), `[%fp-0x2d]`=code,
`[%fp-0x2c]`=value high, `[%fp-0x2b]`=value low. General codes (`code != 2`) reach `DddCmdSetVcp` via the
**`call 0x1869BC` at VA `0x104170`** (`%o0`=code, `%o1`=`%fp-0x2f`). Redirecting that call to a Set hook (reading the
value from `%fp`) adds F0/F1/F4, branching to the real `DddCmdSetVcp` for all other codes. `retl` returns to
`%o7+8 = 0x104178` (the dispatcher's result check `andcc %o0,0xff`).

### Memory read/write command set (F0/F1/F2/F4), scratch in the cave

- **Scratch**: a 4-byte current-address pointer in the free tail of the cave (after the ~52-byte hook; the PDIC stub
  is 0x90 and the adjacent `0x1E4510` stub adds 0x40). First hardware run also confirms code-RAM is writable; if not,
  fall back to a data-region scratch.
- **Set F0** `addr = (addr & 0xFFFF) | (value16 << 16)`; **Set F1** `addr = (addr & 0xFFFF0000) | value16`.
- **Get F2** read 4 bytes at `addr`, place in the reply buffer, `addr += 4`.
- **Set F4** write `value_low` byte at `addr`, `addr += 1`.
- Range-guard the address to the safe RAM window before dereferencing (mirror the LC34's `0x200000..0x7fffff`-style
  guard, adjusted to the G5 map) so a bad read/write can't touch MMIO.

### For the real memory-read step (after the proof)

- **Scratch RAM** for the current address (LC34 used its RAM block): locate a few unused runtime bytes
  (`0xA80xxxxx` globals or spare settings bytes). Next step.
- **SPARC ABI for the hook**: the hook is entered at the Get call site with `%o0`=code, `%o1`=reply buf; it may use
  `%o2..%o5`/`%g1..%g4` freely (caller-saved), must preserve the caller's `%i*`/`%l*`, and ends by either returning a
  value in `%o0` or branching to the real handler. No `save` needed if it stays in the caller's window.
