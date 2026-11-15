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

### Get VCP dispatch (the hook point)

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

## Code-cave strategy (confirmed: the code is packed)

The SPARC code region (file `0x12E000..0x21DCE0`) has **no zero/nop padding runs ≥ 64 bytes** — unlike the LC34's
MStar cave, there is no free padding to inject into. The hook code must therefore **reclaim dead code**: uncalled
stubs the sibling RE flagged (PDIC/TCON/FPGA update stubs with no reachable callers). Confirmed present on our image:

| Candidate | VA | File | Note |
|---|---|---|---|
| PDIC "not implemented" stub | `0x1E45D4` | `0x2125D4` | sibling RE: no callers; logs and returns 0 (string at file `0x319113`) |

Next: confirm no live caller reaches a chosen stub, measure its reclaimable length, and verify r3..r8/r9 usage rules
(the project's hook register discipline) translate to the SPARC ABI before writing into it.
