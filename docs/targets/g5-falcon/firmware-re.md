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

## MEMORY READ VALIDATED ON HARDWARE (2026-11-15)

Image `M-C5500GGZA-1014.0[AE6F]` (memory_hook.py). Over DDC/CI: Set VCP `0xF0/0xF1` set the address, Get VCP `0xF2`
reads 4 bytes (auto-advancing +4). Reading `0x245658` returned `M-C5500GGZA-1014.0` byte-for-byte; stock `0x10`
unchanged. **Arbitrary firmware-memory read over HDMI works — LC34 parity.**

Two runtime facts learned the hard way (both via hardware debug builds):
- **The code region (0x100000..0x2F8000) is READ-ONLY at runtime** (the firmware never stores there). Scratch must
  live in writable BSS.
- **The main app is relocated at runtime**, so absolute references into the code region are invalid (PC-relative
  branches/calls still work). The address scratch is therefore in BSS at `0xA8039A00`, addressed absolutely like the
  firmware's own `0xA80xxxxx` state (those resolve correctly).

Reply byte order (confirmed): the 4 reply bytes map `mem[0]=CL, mem[1]=ML, mem[2]=CH, mem[3]=MH`.

### F4 (write) — guard needs widening
`F4` currently guards writes to `[0x100000,0x2F8000)`, which is the read-only code region, so its writes are no-ops.
The write *mechanism* is proven (F0/F1 write the BSS scratch). To make F4 useful, restrict it instead to a **safe
writable** region (BSS/settings), not the code region — next refinement. Writes to flash (the DDC flasher) go through
the firmware's SPI driver, not direct RAM stores.

## DDC flasher — leads (update A: write bank B; update B: activate)

Flash-related SPARC functions found in the catalog (names from debug-symbol anchors; map directly to our image):

| Symbol | VA | Note |
|---|---|---|
| `SYSAPI_EraseUSRFlashType2` | `0x1720B8` | flash erase (user region) — candidate for bank-B erase |
| `SecLibCommon_GetRomChecksum` | `0x18B9F4` | reads a ROM/flash checksum — useful to verify a written bank over DDC |
| `SecHalUserData_SaveDiffToEEPROM` | `0x124A20` | EEPROM settings writer |
| `SecLibUserData_SaveDiffToEEPROM` | `0x1B5ECC` | EEPROM settings writer |
| `SecAppOsd_DisplayUSBUpdate*` | `0x1D2018`, `0x1E07F0`, `0x1D24B8` | USB-update OSD (version/now/error) — near the real flash-program path |

Most of the SPI flash *program* path is in the 8051 USB updater (record 2); the SPARC app exposes erase/checksum.
Next: disassemble `SYSAPI_EraseUSRFlashType2` and trace the program/page-write routine it pairs with, and the A/B
bank layout, to build a DDC command that streams an image to the inactive bank (via these routines) + a verify
(checksum read-back over DDC), then a separate activate command. High risk — staged and validated before any switch.

### Flash driver primitive (for update A)
`SYSAPI_EraseUSRFlashType2` (0x1720B8) validates a type nibble (0x10/0x30) and calls the flash op primitive
**`0x16892C`** with a command byte (e.g. `0x40`). `0x16892C` indexes a **0x26-byte-stride descriptor table at ~0x204158**
by command and drives the SPI engine from it. So the flash driver is a table-driven command machine. Next: decode the
descriptor table (erase/program/read-status opcodes), find the page-program path and the A/B bank select, then design
update A to copy bank A→B internally and apply only the DDC-sent patch diff (DDC bandwidth makes a full-image stream
impractical). **The flash-program code is the single highest-risk patch of the project — it needs explicit go-ahead
and a careful staged test before any bank switch.**

### Storage subsystem (for the flasher)
The flash-op table at VA `0x204158` (file `0x231E58`, data) is a table of **named storage-region descriptors**
(`DG_EEPROM1`, `OPR_EEPROM_1`, `OPR_EEPROM_2`, ...), 0x26-byte entries. The SPI driver code uses the standard NOR
opcodes (`02` page-program, `20`/`D8`/`C7` erase, `03` read, `06` WREN, `05` RDSR, `9F` JEDEC). The flasher must
select the main-firmware region (bank A/B), not an EEPROM region.

### Plan to minimise USB flashes (user preference)
Do **all** the offline design first and ship **one** bundled image (memory read/write + the DDC flasher's stage/verify
commands), flashed once by USB; after that, patches apply over DDC (fast). The bank-switch/activate stays a separate,
explicitly-approved step. The flash-program code may still need 1-2 hardware iterations despite max static checking.

## All-in-one dev image (minimise USB flashes)
`devtools_hook.py` builds one image (hook in verified-dead `0x1E14EC`, 0x280 bytes) with: memory read (F2) over
[0x100000,0x2F8000)+BSS, memory write (F4) to BSS, and a **call-any-firmware-function** primitive (F5). Slots in BSS
at `0xA8039A00`: ADDR +0, TARGET +4, ARG0..3 +8..+0x14, RESULT +0x18, SAVED +0x1C. Load TARGET/ARGs with F4 byte
writes, trigger with F5, read RESULT with F2. Flashed once by USB, this drives all flasher/8051 experimentation over
DDC (call erase/program/checksum routines live, read results) — no more USB cycles until the hook itself changes.

## ALL-IN-ONE DEV IMAGE VALIDATED (2026-11-15) — memory r/w + call-any-function over DDC
Image `M-C5500GGZA-1017.0[B4B8]` (devtools_hook.py). Over DDC: memory read (data at VA), memory write (BSS), and the
**F5 call primitive returns 1** for the safe target — i.e. we can invoke any firmware function with args and read its
return value, entirely over HDMI. Key runtime fact: **the code region runs relocated by delta = 0x320** (runtime =
file VA + 0x320); the hook measures delta with a PC-relative call and adds it to the target, so targets are passed as
file VAs. Data and BSS are at their VAs. This image drives the rest of the flasher work over DDC (invoke
erase/checksum/8051 paths live), so no more USB flashes until the hook itself changes.

Slot map (BSS 0xA8039A00): ADDR+0, TARG+4, ARG0..3 +8..+0x14, RESULT+0x18, SAVED+0x1C, DELTA+0x20.

## Real firmware function called over DDC (2026-11-15)
Over the dev image, called `SecLibCommon_GetRomChecksum` (0x18B9F4) via F5 and read RESULT = **0xC145** — the stored
whole-file check marker of the stock image. Confirms the call primitive works on real firmware functions (delta 0x320
applied, return captured); stock VCPs unaffected. Note GetRomChecksum returns the stored marker, not a live sum, so
a live-verify for the flasher will need to compute over the written bank instead. Next flasher steps (erase/program)
are flash writes -> gated on explicit user go-ahead.

### Flash driver chain mapped (for the DDC flasher)
Storage descriptor table (0x204158) only holds EEPROM regions (DG_EEPROM1, OPR_EEPROM_1/2/3) — not the main
firmware. The SPI driver chain is: `SYSAPI_EraseUSRFlashType2` (0x1720B8) -> flash-op primitive `0x16892C` -> raw SPI
`0x1509E8` -> **platform services at 0xA002xxxx** (the HAL that pokes the SPI hardware; same region as the UART/other
services). To write bank B from the SPARC we must drive this chain (or the raw SPI) at a bank-B address rather than
via the EEPROM descriptors. Next (offline): decode the 0xA002xxxx SPI service args (register/opcode/data) to see if a
raw page-program at an arbitrary address is callable. Any actual flash write is gated on explicit user go-ahead.

## DDC flasher — SAFETY PROTOCOL (hard rules, user-approved 2026-11-15)
Bank-B approach; the active-slot tag is always the LAST write. Rules, in order:
1. **Full SPI-flash backup over DDC before ANY write**, read-only (via memory-read / call-any-function). Store under
   `data/` (NEVER commit). Verify: read twice, hashes must match; sanity-check against stock `1008.3[C145]` for the
   regions that must be identical. The backup must be restorable with an external CH341A + SOIC-8 clip in a worst-case
   brick.
2. Re-take/verify the backup before every write session (or confirm the existing one still matches).
3. Prove the SPI path with **read-only ops first** (JEDEC id, read status register, read back known bytes) before any
   erase/program.
4. **Hard address guard**: refuse any erase/program outside **bank B**. Never touch the boot / 8051 / USB-updater
   region, the A/B active-slot tag, or the SPI status/write-protect bits — except the final activation write.
5. Verify bank B by checksum/readback against the intended image **before** writing the active-slot tag (always last).
6. Every real flash write needs the user's explicit OK **in the moment**.
Fallback rescue: the stock `.img` flashed over USB.

### Phase 1 (now, read-only): build flash-read-over-DDC + full backup
Need a way to read the raw SPI flash over DDC: either the flash is memory-mapped (read directly, may need widening the
read guard) or call a firmware SPI-read routine into a RAM buffer, then memory-read the buffer. Then dump all 8 MB and
verify. All read-only.

## BREAKTHROUGH: SPI controller is MMIO-mapped (drivable over DDC)
`0x126A2C` is a register-access dispatcher: `reg_op(idx<=0x11, v1, v2)` jumps via a table (base `0x49a<<10|0x78 =
0x126A78`) and writes the **SPI controller MMIO registers at ~0xCF03Cxxx** (`sethi 0x33c0f0 -> 0xCF03C000`, handlers
store to 0xCF03C2C0, 0xCF03C31C, ...). The low-level SPI helpers (0x1509B0/E8, 0x15E560) toggle chip-select and push
bytes via this and the 0xA002xxxx HAL. So the SPI flash controller can be driven **directly by memory read/write to
0xCF03Cxxx over DDC** — raw SPI commands (JEDEC 0x9F, RDSR 0x05, READ 0x03, WREN 0x06, PP 0x02, SE 0x20) at arbitrary
addresses. This is the cleanest path (no cross-region call relocation): read for backup/verify, write for bank B.

Plan: (1) map the SPI reg layout from 0x126A2C's jump table (cmd/data/status/CS regs); (2) a hook that allows R/W of
the SPI MMIO window only; (3) read-only JEDEC/RDSR proof over DDC; (4) flash read (backup/verify); (5) bank-B
erase/program with the hard address guard; (6) activation last. All writes gated per the safety protocol.

### SPI controller register map (MMIO)
The reg-op dispatcher `0x126A2C` writes the SPI controller registers in **0xCF03C2C0..0xCF03CC8C** (data/cmd/ctrl/CS
set). The low-level helpers wrap these with CS toggling (0x1509B0/E8) and a byte-send (0x15E560 drives regs 0x13/0x14
via the 0xA002xxxx HAL). Driving raw SPI register-by-register over DDC is possible but fragile/risky, so prefer the
firmware's own high-level flash routines (addr+buf+len) used by the USB updater — to be located next (SPARC update
data dispatch 0x18E274 / external-FW wrapper, or an 8051 program routine).

## Flash is NOT memory-mapped (hardware-confirmed 2026-11-15)
Over the 1018.0 (read-any) hook, probed candidate flash windows (0x0, 0x04/08/10/20/40/80/A0/B0/C0/D0/E0/F0 000000):
none show the NVTSC magic; mostly 0x00/0xFF (0xA0000000 = RAM, 0xD0000000 = MMIO). So the SPI flash is not readable by
a plain memory read — we must drive the SPI controller. The controller regs at 0xCF03Cxxx read 0 via byte loads (MMIO
likely needs 32-bit word access). Reads of unmapped addresses were safe (no hang).

Path chosen (safer): drive SPI by **calling the firmware's register functions over DDC** (0x126A2C writes a reg;
find its read counterpart) rather than hand-poking MMIO. Decode the SPI command sequence (CS, opcode, address, data,
status) starting with a read-only JEDEC (0x9F) / RDSR (0x05) proof, then flash read (backup/verify), then bank-B
erase/program under the address guard.

## DDC main-firmware flasher — feasibility conclusion (2026-11-15)
After exhausting the angles (memory-mapped flash, high-level flash funcs, 8051 path, direct SPI), two hard walls make
a practical DDC flasher for the MAIN firmware infeasible:
1. **No SPARC flash R/W API**: the SPARC exposes only EEPROM-region erase; main-firmware flash R/W lives in the 8051.
   The only SPARC/DDC route is driving the SPI controller register-by-register (2+ HAL layers at 0xA002xxxx +
   0xCF03Cxxx) — very deep and, for writes, real brick risk.
2. **DDC bandwidth**: DDC moves ~4 bytes/transaction (~0.1s). JEDEC/status/a few KB are fine, but programming bank B
   (3.4 MB) or a full backup over DDC would take **days**. The channel isn't suited to MB-scale transfers.
Recommendation: **consolidate the achieved HDMI control** (memory read/write, call-any-function, read-any-address —
all validated) and keep **USB** as the firmware-flash path. The DDC flasher is not pursued further.

## REOPENED (Fable strategy): internal flasher, read-only SPI proof first
Fable's plan reframes the bandwidth wall: the flasher runs AS firmware code in a dead-code cave (code RAM is
executable-but-RO; BSS is writable but executability unproven -> code stays in the cave, BSS only for data staging),
triggered by one F5; it copies bank A->B, applies the DDC-staged diff, programs and verifies bank B INTERNALLY (only
trigger + ~500B diff cross DDC). Preferred write path: compose a raw page-program (0x02) from the firmware's own SPI
primitives (address-agnostic -> bank B directly). Recovery = stock USB .img + A/B invariant (don't touch bank A or the
tag until verified). All validated read-only first.

### SPI primitive map (for composing commands via F5, no reflash)
- ~~`0x15E560(byte)` = send one SPI byte~~ **WRONG — it is 8051 mailbox "set FE2P address" + "erase sector"; see "SAFETY CORRECTION" below. Never call it.**
- `0xA002CBD4(reg,..)` = HAL **register READ** (0x1509E8's ready-poll reads reg 0xc until bit0==1). [HAL region, call via
  the SPARC wrappers, not directly — different relocation than the 0x320 code delta.]
- Reg `0xc` = SPI control / chip-select (0x40 idle, 0xc0 active); regs `0x13/0x14` = SPI data.
- `0x1509E8` = CS toggle + wait-ready poll; `0x1509B0` = short CS op.
Next (read-only, current image): find CS assert/deassert + read-byte SPARC wrappers (or a high-level SPI read fn), then
drive JEDEC 0x9F / RDSR 0x05 / READ 0x03 via F5 and read results from BSS via F2. A sane JEDEC id proves SPI control.

### Read-only SPI JEDEC experiment (2026-11-15, dev image 1018.0)
Drove 0x1509E8 (prep) + 0x15E560(0x9F) + 0x15E560(0x00)x3 via F5. All rx read as 0x00 -> **0x15E560 does NOT return the
received byte**; the SPI RX byte must be read from the data register separately. The monitor stayed healthy (clean
re-test after: fw string ok, safe call RESULT=1, delta=0x320, brightness ok) — the SPI calls were harmless.
Two paths to read the SPI RX: (A) a SPARC wrapper that reads the SPI data/status reg, callable via F5 (the HAL reg-read
0xA002CBD4 is in the 0xA002xxxx region with a different relocation than the 0x320 code delta, so not directly F5-able);
(B) add 32-bit MMIO read/write to the hook (reflash) and drive the SPI controller regs (0xCF03Cxxx) directly. Pursue A
first (no reflash).

### Blind HAL experiments don't work; monitor self-recovers (2026-11-15)
Driving SPI by calling HAL funcs (0xA002EF00/0xA002CBD4) with guessed args from the host transiently corrupts state
(reads briefly return 0 / delta 0) and does NOT reveal the RX register. The monitor **self-recovers** every time
(firmware main loop re-inits) — confirmed: fw string/brightness/input all OK after. So the experiments are safe but
unreliable. CS can be held across F5 calls via 0x126A2C(0xc,0xc0) (assert) / (0xc,0x40) (deassert), but reading the RX
byte needs the exact HAL read convention, which blind calls don't give. **Correct path:** statically reverse the
firmware's own flash/EEPROM READ (0x1689FC family) to extract the precise CS/send/recv sequence, then put a complete
SPI-transaction routine in a hook (CS held internally) — reliable, no host-side guessing. That routine is also the
internal-flasher building block. Needs a hook change (reflash) once designed.

## SPI controller MMIO is READABLE over DDC via 32-bit word access (hardware-confirmed 2026-11-15)
Dev image **1019.0[AE8D]** (devtools_hook.py) adds **F3** (Get: single 32-bit word read at ADDR, any address) and
**F6** (Set: write staged 32-bit VALW to [ADDR], guarded to the SPI window [0xCF03C000,0xCF03D000)). Flashed by USB.

Confirmed on hardware (AMD HDMI DDC link, all transactions `st=0`, monitor healthy throughout):
- **F3 works**: reading a known RAM word via F2 (4 byte-loads) and F3 (one word-load) returns the identical value.
- **The SPI controller registers now read real values** (byte-loads returned 0; the record's open question). 32-bit
  read of 0xCF03C000 = 0x23, +0x00C = 0x61, +0x2C0 = 0x0C, +0x030 = 0x7F, etc. A read-only sweep of
  [0xCF03C000, 0xCF03CD00) step 4 shows a dense byte-register file (every non-zero reg is a value <=0xFF at a
  4-byte stride): this is the scaler register space; the SPI engine is a cluster within it.
- **DDC reply byte order (F2/F3)**, calibrated: from the 11-byte Get-VCP reply `6E 88 02 00 <vcp> 00 b6 b7 b8 b9 ck`,
  the memory bytes are `mem0=b9, mem1=b7, mem2=b8, mem3=b6`; F3's 32-bit word (big-endian) = mem0<<24|mem1<<16|mem2<<8|mem3.
- **Memory-read relocation for CODE**: a runtime read at code VA X returns the byte the image has at file
  `(X-0x320)+0x2E000` (i.e. code runs relocated by +0x320, so a runtime read of VA X sees nominal VA X-0x320). Data/BSS
  unaffected. (Calibrated: runtime read of 0x200004 = image[0x22DCE4].)

### SPI controller register map (reg_op dispatcher 0x126A2C), decoded from the flat image
`reg_op(idx<=0x11, v1, v2)` is a **write-only** register setter: it `and`s v1,v2 to bytes and stores each to a pair of
mirror MMIO regs in the 0xCF03Cxxx file (e.g. idx-0 case -> 0xCF03C2C0=v1, 0xCF03C31C=v2; other cases hit
0xCF03CC8x/CCCx and 0xCF03C4xx banks), then `retl` (returns %o0 unchanged — it does NOT read). The **read** counterpart
is a separate dispatcher at **0x126C74** (`reg_read(idx)`, table at VA 0x1268C0). `0x1509E8` (CS + ready poll) drives
`reg_op(0xc,0x40)`=CS idle / `reg_op(0xc,0xc0)`=CS active, then polls up to 9x; `0x15E560(byte)` drives idx 0x14 (data)
then idx 0x13 (trigger). Next: decode `reg_read` (0x126C74) to name the RX/status reg, OR (safer) drive the firmware's
own flash-read routine (GetRomChecksum 0x18B9F4 already reads flash over DDC via F5, returning 0xC145) to read
JEDEC/backup bytes into a RAM buffer, then F2-read the buffer. No flash write has been issued; all work read-only.

### Correction to earlier SPI inferences (hand-decode, 2026-11-15)
Decoding the SPI stack from the flat image revealed the earlier record inferences were partly wrong:
- `reg_op` (0x126A2C) is **write-only** (stores v1,v2 to mirror regs, returns %o0=idx unchanged). The "ready poll"
  in `0x1509E8` therefore **never reads a status bit** — it compares reg_op's return (the idx 0xc) to 1, never equal,
  so it is just a fixed ~9-iteration delay loop of CS toggles, not a poll. The `reg_read` dispatcher at 0x126C74
  returns **constants** per idx (no MMIO load), so it is not the RX path either.
- `0x15E560` ("send byte") does `reg_op(0x14,0,0)` then `reg_op(0x13,0,2)` — the data byte (o3) is **not** passed to
  reg_op as decoded, so its exact data path is unclear by hand-decode.
- `0x16892C`/`0x1689FC` are **descriptor-table-driven** storage ops (region table at 0x810158, 0x26-byte entries),
  not a general (addr,buf,len) flash read/write.
Conclusion: the low-level SPI transaction must be decompiled in **Ghidra** (clean decomp of the TX/CS/RX registers)
before a JEDEC/RDSR read-only proof or any SPI-register-driven write can be composed reliably. Hand-decode is
error-prone here. The NEW, solid capability this session is **reliable 32-bit MMIO read of the SPI controller over
DDC (F3)** — enough to observe the engine; the write/trigger sequence is the remaining unknown.

## SPARC <-> 8051 flash architecture (2026-11-16, overnight RE session)

### SAFETY CORRECTION — `0x15E560` is NOT "send one SPI byte"
`0x15E560(v)` = `HAL_mbox(0x14, 0, v>>8, v&0xFF, 1)` + `HAL_mbox(0x13, 0,0,0, 2)` = **8051 "set FE2P address" +
"erase 4 KB sector"**. The 2026-11-15 "JEDEC experiment" (calling it with 0x9F and 0x00) therefore asked the 8051 to
erase up to two 4 KB sectors **inside the FE2P (flash-emulated EEPROM) window** — settings storage, not firmware. The
unit has since booted a USB-flashed image normally (boot/app intact). Worst case: some saved settings reset. **Never
call 0x15E560, 0x15E524 (program), 0x15E5C4 (write bytes), or any wrapper that sends cmd 0x11/0x13/0x15/0x07.**

### Ghidra setup (local, `data/` ignored)
- `data/ghidra-g5` (processor `sparc:BE:32:default`): `data/vendor/g5/g5-va-0x100000.bin` (image code+data laid
  out at VA, base 0x100000) plus the **HAL dump** (`data/vendor/g5/hal-a0028000.bin`, runtime 0xA0028000..0xA0031000,
  read over DDC with `tools/windows/experiments/g5/g5-dump.ps1`, 0 failures, 7 independent probes match) loaded at
  **0xA0027CE0** (= runtime − 0x320) via `tools/ghidra/AddBlock.java`, so the code's PC-relative calls resolve.
- `data/ghidra-8051` (processor `8051:BE:16:default`): 8051 runtime firmware = image file `0x8060..0x17B40`
  (code base 0, reset `LJMP 0xBACE`). Seeded at the vectors + handler entries.

### Why the HAL calls looked wrong: absolute HAL + relocated code (confirmed)
The SPARC app runs at file-VA + 0x320 (known). Its `call` to the HAL (0xA002xxxx) is PC-relative, so the real callee
is the **image target + 0x320**: e.g. `call 0xA002EF00` executes `0xA002F220` (`save` prologue, confirmed in the dump);
the bytes at the nominal address belong to a different function. All HAL entries in this doc are nominal (link view).

### The HAL mailbox to the 8051 (confirmed: bytes + decompilation)
`HAL_mbox(cmd, b1, b2, b3, mode)` (nominal 0xA002EF00): waits (<=100 polls) for mailbox word[0]==0, writes
`b3<<24|b2<<16|b1<<8|cmd`, then mode 2 = handshake on word[0xB8] (set low byte 1, wait for 2), modes 1/2 = wait for
word[0]==0 again, **mode 3 = spin forever** (power-off/power-save hand-off). Mailbox read/write helpers (nominal
0xA002C414 / 0xA002C4EC) use bank 0 base **0x9F0A0100** (`sethi 0x27c280; or 0x100`) and bank 1 base 0x9F130100.
Read over DDC (F3, read-only): word[0]=0 (idle), +0xB8=0x200; the bank-0 region also holds our own DDC/CI frames, so it
is a shared buffer. Hypothesis "0x9F0A0000 is the whole 8051 XDATA" was **tested and rejected** (XDATA 0xA4xx/0xA7xx
read as zero there).

SPARC mailbox API module = **0x15DE00..0x15F970** (one small wrapper per command; 45 call sites). Named ones:
`0x15E490 MailBox_LoadFE2P(offset16, len)` = cmd 0x14 + cmd 0x12 (read; modes fixed 1/2 inside);
`0x15E524` = cmd 0x14 + cmd 0x11 (**program**); `0x15E560` = cmd 0x14 + cmd 0x13 (**erase**);
`0x15E5C4` = cmd 0x14 + cmd 0x15 (**write bytes**); `0x15FB9C(n-1, dir, buf)` pushes data SPARC->8051 in 16-byte
slots (header `cmd 7`) at mailbox +0x10+k*0x14; also DCoffTimer (0x26), SetWakeUpTimer (0x1C), Set Indicator
(0x18/0x19/0x1A), internal EDID (0x01/0x0E), power-save/off (0x16/0x17, mode 3).

### 8051 runtime: mailbox dispatcher and flash routines (confirmed by decompilation, names from its strings)
Dispatcher: `mov a,r3; dec a; cjne a,#0x2A; mov dptr,#0x27B6; mul ab(x3); jmp @a+dptr` -> commands 1..0x2A.
| cmd | 8051 handler | meaning |
|---|---|---|
| 0x14 | 0x28DC | `addr(a75b..e) = FE2P_BASE(a757..a) + offset16`; optional len; prints "Update FE2P Addr %08lx"; replies addr at +0xB4 |
| 0x12 | 0x290A | read flash at addr (`0x8145`, "read flash flashaddr %08lx, Length %d"), checksum (`0xC912`), reply at +0xB0 |
| 0x13 | 0x291B | erase: `0x9766` ("DoBlockErase"), opcode 0x20 (4 KB) / 0x52 (32 KB) / else 64 KB; WREN first |
| 0x11 | 0x28FF | program (`0x77C9`): 8051 SPI controller XDATA `F1C0`(ctrl)=0x82, data to `F1C3`, WREN (`0xEE5D(6)`), busy-wait (`0xE876`) |
| 0x15 | 0x2926 | write bytes (`0xB1A8`) via the program path |
| 0x16 / 0x17 | 0x2949 / 0x297B | CMD_SYS_POWERSAVING / CMD_SYS_POWEROFF |
| 0x1D / 0x1E | 0x2A08 / 0x2A33 | CMD_SET_P14 / P15 = drive 8051 port pins P1.4 / P1.5 (GPIO, not "parameter 14") |
| 0x21 | 0x29A6 | CMD_WRITE_DPTXHDCP |
The read path (`0x8145`) issues **no** WREN/erase/busy-wait (only print, generic loads, Keil math) — read-only.
**FE2P_BASE is written exactly once, at boot** (`0xE9CF` "FE2P_SetLeon2BaseAddress %08lx", from the bootloader-shared
structure at XDATA ~0xA794, which is only read). No mailbox command changes it.

### Consequence for the DDC flasher (inferred from the above, high confidence)
With the stock 8051, mailbox flash ops are **confined to the 64 KB FE2P window**; there is **no stock DDC path to bank B,
and no JEDEC command**. The 8051 owns the flash (its runtime has the JEDEC "Flash Info", WREN, erase, program, quad-mode
code). Realistic flasher routes, in order of preference:
1. **Vendor dual-FW updater path** (8051 segment B, file 0x17B40.., banked): `CMD_LOADFILE2DRAM`,
   `CMD_START_ISP_ROMCODE_MODE_DUALFW`, `TagInfo.ValidRegionNext/Current`. If it programs the inactive region from
   DRAM, the SPARC could stage the image in DRAM (the running image + a small diff) and trigger it. Next RE target.
2. **Patched 8051 runtime** (USB-flashed) adding a "set FE2P base" / 24-bit-address mailbox command, so a SPARC hook
   drives the 8051's proven erase/program/read anywhere (internal A->B copy + DDC diff). Needs proof first that a
   broken segment-A cannot block the USB updater (segment B) — otherwise it is an unrecoverable-brick risk.
3. Direct SPARC access to the 8051 SPI controller registers (XDATA F1C0..) if a SPARC-visible alias exists (unproven).
Ready-to-run read-only proof for a supervised session: F5 `MailBox_LoadFE2P(0, n)` then F3 read of 0x9F0A01B0
(checksum) — not run unattended because its effect on the 8051's in-RAM settings copy is not fully known.

### 8051 register page is visible to the SPARC; the SPI command engine (confirmed / negative result, 2026-11-16)
- **Mapping (confirmed):** 8051 XDATA register `X` (page 0xF000..) appears to the SPARC at `0xCF000000 + X*4`
  (byte register, 32-bit access). Evidence: SPARC `USBCop_ConfirmInit` clears `((0xF190+i)*4)|0xCF000000`; DDC reads
  give XDATA F050=0x15 and F0DD=0x04 at 0xCF03C140 / 0xCF03C374, consistent with the 8051 main() logic. So the
  "SPI controller at 0xCF03Cxxx" of earlier notes is the 8051's register page F000..F3FF. The 8051's **RAM**
  (0x3000, 0xA4xx, 0xA7xx) is **not** visible there (reads 0).
- **SPI command engine (from 8051 0xEE5D / 0xE876 / read 0x8145):** F0E5 start (1 = opcode only from F0EE, 2 = opcode
  from F0EA + read phase; busy while bit0/bit1), F0E6 mode (`&0x0C | 0x41` command, `|0x01` read), F0EB..ED address,
  F0F4 read config (7 status read, 0x0B data read), F0EF result byte, F1C0 data-buffer control (0x81 capture, 0x82
  read-out). Read opcode chosen at boot from F050: 0x0B / 0x3B / **0x6B (quad, active: F050 bit2=1)**. The SPARC app and
  HAL never reference these registers.
- **Read-only JEDEC attempt via the 1019.0 hook (`tools/windows/experiments/g5/g5-spi-id.ps1`):** replicated 0xE876
  with opcode 0x9F/0x05 under hard guards (register allowlist, F0EE never written, F0E5 only 2, staged values read back,
  originals restored). Result: F0EF stayed at its prior value 0x08 for every op; restore left all registers identical.
  Follow-up: F6 writes of 0x05 to F0EA and 0x07 to F0F4 do not change their read-back, although the 1019.0 F6 handler is
  correct in the flashed binary (guard [0xCF03C000,0xCF03D000), `st VALW,[ADDR]`) and the dispatcher does not filter
  code 0xF6. **Conclusion: SPARC stores to the 8051 SPI-engine registers have no visible effect** — most likely a
  hardware write block (flash reachable only through the 8051), but **unconfirmed** until F6 is positively tested on a
  benign SPARC-writable register (the obvious GPIO candidates include the flash write-protect line — not touched
  unattended). No flash command was issued (by construction the engine could only have sent 0x9F/0x05).

### Container record table and flash map (confirmed from bytes, 2026-11-16)
Each record has a 32-byte header right before its data: `u16 f0, u16 f1, u32 size, u32 checksum, 0x04000000, 16x 00`.
`(f0<<16)|f1` is the **flash destination** (the SPARC code record gives 0x108000, the known target). For the 8051 and
small records the checksum is the **sum16 of the record data** (verified for all 8; the SPARC records carry 0xFFFFFFFF).
A patched record must update this per-record checksum as well as the whole-file sum16 / filename tag.

| Header | Flash dest | Size | Content |
|---|---|---|---|
| 0x000020 | 0x000000 | 0x8000 | 8051 **boot** (checks A/B tag at flash 0x7FFF == 0xAA, picks bank) |
| 0x008040 | 0x010000 | 0xFAC0 | 8051 **runtime** ("segment A": mailbox, FE2P, SPI engine) |
| 0x017B20 | 0x020000 | 0xC180 | 8051 **USB updater** ("segment B": CMD_LOADFILE2DRAM / START_ISP_ROMCODE_MODE(_DUALFW), TagInfo) |
| 0x023CC0 | 0x0D0000 | 0x7760 | unknown |
| 0x02B440 | 0x0FC000 | 0x2860 | unknown |
| 0x02DCC0 | 0x108000 | 0x1F0000 | SPARC code |
| 0x21DCE0 | 0x2F8000 | 0xFB9C0 | SPARC data |
| 0x3196C0 | 0x050000 | 0x2FB00 | unknown |
| 0x3491E0 | 0x0A6000 | 0x1120 | unknown |
| 0x34A320 | 0x006000 | 0x60 | small block inside the boot sector (config / shared structure?) |
Everything sits below 0x400000, consistent with a second bank at 0x400000 (still inferred).

### USB updater ("segment B", flash 0x20000) — what it does (confirmed by disassembly)
Command byte at its XDATA 0x08E8, status at 0x08E7: `0x46` CMD_LOADFILE2DRAM (`0x7B97`, status 0x97 = loaded),
`0x16` CMD_START_ISP_ROMCODE_MODE / `0x17` ..._DUALFW -> `0x8656(0x10 / 0x11)`, then it **polls register F19A**
(bits 0..2 = stage 1..4 -> status 0xC1..0xC4, `&0x8F == 0x8F` = done), status 0x99, and parks in a self-loop. So the
8051 **does not program the flash itself** in an update: it starts a **ROM-code ISP** (the chip mask ROM, not present
in the image) and watches its progress. DUALFW first reads TagInfo (`0xAA6B`: for region k in {0,1}, read flash at
`base + k*0x1000 + 0xFFF`, valid if 0xAA; ValidRegionNext = (current+1) % 2). F190..F19F / F1E0 / F1EB form a shared
update register block (the SPARC's `USBCop_ConfirmInit` clears F190..F19F). How the SPARC hands control to the
updater, where the image lands in DRAM, and what the ROM ISP expects are the open questions for a vendor-path flasher.

### 8051 boot bank selection and the region descriptor (confirmed from bytes; bank-B location still inferred)
Boot entry (flash 0, file 0x40): `mov dptr,#0x7FFF; movc; cjne a,#0xAA` -> offset 0x1000 if the tag is 0xAA, else
0x0000; then it reads a **descriptor table at 0x6000 + offset** (0x6000 = region A, 0x7000 = region B). The image
carries only the region-A table (record -> flash 0x6000, 0x60 bytes): big-endian `(u32 flash address, u32 size)`
pairs — 0x010000/0xFAA7 (8051 runtime), 0x020000/0xC16B (updater), 0x0D0000/0x775C, 0x0FC000/0x2858,
**0x108000/0x2EB9AC (whole SPARC app)**, 0x050000/0x2FAF0, 0x0A6000/0x1108, 0x030000/0xF9F0, 0x0B0000/0x1CDCC
(the last two are not in the update image), then 0xFF padding. Activating a new bank therefore means: write its images,
write its descriptor (0x7000 for region B), verify, and only then flip the tag byte at 0x7FFF — the "tag last" rule of
the safety protocol maps onto exactly this byte.

### F6 positive control: SPARC writes reach F19x but not the SPI engine (confirmed on hardware, 2026-11-16)
F6 wrote 0x5A to XDATA **F19F** (SPARC 0xCF03C67C; used only by the USB updater and the SPARC USB-update code, never by
the running 8051 runtime or boot) and it **read back 0x5A**, then was restored to 0x00. The same F6 path does not change
F0EA / F0F4 (SPI engine). So: **F6 works, and the SPI-engine registers ignore SPARC writes** (a hardware write block
is the natural reading: the SPARC can never drive the flash directly). Conversely the SPARC **can write the updater's
command block F190..F19F**: the updater copies its command from **F191** (`0x4672`: `08E8 = F191`) and reports status
through F190/F192/F193 — this is the channel the SPARC's `USBCop_*` code uses during a USB update, and the lever for a
vendor-path flasher once the updater is running. Open: how the SPARC switches the 8051 from runtime to updater, and
where the image is staged in DRAM for the ROM-code ISP.

### 8051 boot loader and the runtime -> updater hand-off (boot confirmed by decompilation; hand-off inferred)
Boot (`flash 0`, built "Aug 17 2022"): Keil startup -> `main 0x0F3F` -> `0x0003` reads the tag (0x7FFF), picks the
descriptor (0x6000/0x7000), fails with "Can't find valid partition table!!!" if it is bad, copies the descriptor into a
shared structure at its XDATA 0xA000.. (which also carries opcodes such as 0x9F), then programs **F1D3..F1D5 = start
address** ("FLASH_ADDRL/M/H") and **F1D6..F1D8 = length** ("BOOT_DATA_LENGTHL/M/H") of descriptor entry 0 (the runtime,
0x010000) and prints "Re-booting STBC code..." — i.e. **the hardware loads that flash block into 8051 code RAM and
restarts the 8051** (the 8051 runs from RAM, which is why it can use the SPI engine freely).
Inferred hand-off for a USB update: point F1D3..F1D8 at descriptor entry 1 (updater, 0x020000 / 0xC16B) and warm-reset
the 8051 (the runtime has "0x4570[5] toggle ==> warm Reset!!"; the SPARC `USBCop_ConfirmInit` writes 0xCF011F80=0x80,
clears F190..F19F and toggles F1E0 bits 0/1; the updater's ISP start writes D7E0=0x81, F1EB=0x8A/0x82, F1E0=2/10).
All of these are in (or next to) the SPARC-visible register page, but whether SPARC writes to F1D3..F1D8 / F1E0 are
accepted (unlike the SPI engine) is untested. A further, speculative lead: "ISP ROMCODE mode" may be the chip's
mask-ROM ISP that Novatek factory tools drive over DDC; if the updater's ISP start makes a new I2C slave appear, a true
DDC flasher would use the vendor ISP protocol (with our tag-last discipline).

## DDC flasher — design options after the 2026-11-16 RE (decision needed; no 1020.0 built yet)
Facts that constrain every design: the SPARC can never touch the flash (SPI engine ignores SPARC writes); only the 8051
can, either through its runtime mailbox (FE2P window only, base fixed at boot) or by starting the ROM-code ISP from the
USB updater. DDC moves ~4 bytes per transaction, so any route must keep the bulk copy inside the chip.

| Route | How bank B gets written | What a 1020.0 hook would add | Main risk |
|---|---|---|---|
| A. Vendor updater + ROM ISP | SPARC switches the 8051 to the updater (F1D3..F1D8 + warm reset, to be proven), stages the image in DRAM where CMD_LOADFILE2DRAM puts it (mostly a copy of the running image + small diff), sends 0x17 (DUALFW) via F191; the ROM ISP programs the inactive region and the tag | F6 allowlist widened to F19x / F1D3..F1D8 / F1E0 / F1EB (+0xCF011F80, 0xCF035F80 if needed), a DRAM write/copy primitive (memcpy via F5 + diff writes outside BSS) | low brick risk (vendor dual-FW logic, old bank stays valid until the tag flips); unknown ROM-ISP contract |
| B. Patched 8051 runtime (USB flash once) | add a mailbox command "set FE2P base / 24-bit address" to the runtime; a SPARC hook then copies bank A->B with the 8051's own erase/program/read, applies the DDC diff, verifies, writes the 0x7000 descriptor, flips 0x7FFF last | mailbox primitive with a hard bank-B address guard + tag-last state machine | runtime record is shared by both banks? must prove a broken runtime cannot block the USB updater before flashing it |
| C. Vendor ISP over DDC | if "ISP ROMCODE mode" exposes a new I2C slave, use the Novatek ISP protocol over DDC | none (host-side tool) | entering ISP mode without a way back = needs the USB stick as recovery |

Supervised next steps (each one only with the user present, in this order):
1. Read-only: `F5 MailBox_LoadFE2P(0, n)` -> F3 0x9F0A01B0 (checksum) to prove the SPARC->8051->flash read path end to end.
2. Read-only: snapshot F1D0..F1E0 and 0xCF011F80 / 0xCF035F80 now, to compare with values during a real USB update.
3. Capture a real USB update's register traffic (poll F190..F19F / F1E0 over DDC while the monitor updates from the
   stick) to learn the hand-off and the ROM-ISP status sequence without guessing.
4. Then choose A or B and build 1020.0 for it.

## Supervised session 2026-11-16 (user present): FE2P read, slot collision, vendor USB-update protocol

### DDC pitfall: stale replies (confirmed on hardware)
With the monitor in standby, or busy right after an F5 call, the DDC/CI reply buffer keeps returning the **previous**
frame. A stale F3 frame passes GetF's header/checksum/vcp check, so a whole snapshot read as `0x14` while the monitor
was off. Fixes in `g5-ddc.ps1`: refuse to start unless VCP D6 gets a fresh reply; `RdWF` does a standard VCP query
before every F3 read. Read-only tools added: `g5-snap.ps1` (words / 8051 XDATA registers) and `g5-fe2p-read.ps1`.

### SAFETY: the 1019.0 hook slots overlap a live settings table (confirmed on hardware)
RAM 0xA8039910.. holds an array of 16-byte settings records (values such as 0x32 = 50, repeated per mode). The hook's
SLOTS (0xA8039A00 + 0..0x27) sit **inside** it: every SetAddr writes ADDR over a record word, and F4/F5 staging writes
TARG/ARG/VALW over record bytes. After `F5 MailBox_LoadFE2P(0, 0x10)` the area was rewritten with normal-looking
settings bytes (our staged values gone; only the ADDR word keeps 0xA8039A00), i.e. the settings were reloaded — strong
(inferred) evidence that the SPARC -> 8051 -> flash read path works end to end; the mailbox reply words read 0 by the
time they were sampled. Consequences: a power cycle without touching the OSD reloads clean settings; **1020.0 must move
SLOTS to verified-free RAM** (the same overlap explains why F5 must not run while the firmware reloads settings: SAVED
lives there too). The F5 call returned normally; DDC was busy ~1-2 s afterwards.

### Vendor USB update, SPARC side (confirmed by disassembly; module 0x14C000..0x14EA00)
The SPARC drives a "USB Cop" (the 8051 updater code) through the F19x block: command byte -> **F191** (0x48 / 0x45
get file FW version, 0x46 = CMD_LOADFILE2DRAM), sub-requests/handshake -> **F198** (0x56/0x55/0x54/0x53 read version
bytes, 0x5B/0x5A, 0x52), status <- F190 / F198, file location and size <- **F19B..F19E**. Then
"17 pro": the SPARC enables a **DRAM access port** (`0xCF011F80 = 0x81`) and byte-sums the loaded file, `size/32` lines
starting at **line address (n << 16)** (n and size from F19B..F19E), compares with the checksum in the file name tag
(`[AE8D]`), prints "CKS or DDR error" on mismatch, and on success calls `0x14D004 USBCop_ConfirmInit`:
`0xCF011F80 = 0x80`, F1E0 &= ~2, clear F190..F19F, F1E0 = (F1E0 & ~1) | 2, HAL call (nominal 0xA002E0F8), then the
SPARC spins forever while the 8051 updater / ROM ISP programs the flash from DRAM.

DRAM access port (from `0x141010`, `0x1413EC`, `0x1415C8`, `0x141750`): line address (32-byte lines) in
**0xCF011FA0/A4/A8/AC** (bytes 0..3); **read**: F84 = 0x80, F8C = 0x80, wait F90 == 0x80, then 32 bytes from data port
**F94**; **write**: F84 = 0x80, then bytes to data port **F88**. F80 = 0x81 while the update path uses it. The SPARC
can therefore **write the staging DRAM itself**: route A no longer needs the USB stick, only (1) the staging line
address the updater uses, (2) the file bytes in DRAM, and (3) the state the 8051 updater expects before ConfirmInit.

### Route A, concrete (inferred; next to prove)
1020.0 hook: SLOTS moved to free RAM; a DDC block-write (32 bytes per frame) into the DRAM port; an in-chip copy from
SPARC RAM into the port (F5 on `0x1415C8`) for the code record (identical to the running code); then the vendor
checksum + ConfirmInit sequence. Still unknown: the staging line address and the updater's own state before
ConfirmInit (it normally loaded the file itself, status 0x97). Fastest way to learn both: poll F190..F19F (+ F1E0)
over DDC during a real USB update of the **same** 1019.0 image (needs the user's in-session OK; it is a real flash
through the vendor path).

### First USB-update capture over DDC (2026-11-16, user-run update to 1019.1)
1019.1 = 1019.0 with only the version digit changed (one byte, file 0x273369; the 1019.0 rebuild reproduces the flashed
hash). `g5-watch-update.ps1` (~3 s per register cycle) logged:
- stick with **1019.0** (same version): F19A..F19D = `2E 69 6D 67` (".img", file-name bytes reported by the USB Cop),
  F1E0 = 0x02, 0xCF011F80 0x81 -> 0x80, F190 = 0x96 -> 0x82; no update (refused as same version), DDC kept working.
- stick with **1019.1**: F190 = 0x96, file-name bytes again in F19C, 0xCF011F80 0x00 -> 0x80, F1E0 -> 0x02, then **DDC
  silent ~65 s** (load + ISP + reboot), then everything back to 0 and 0xCF011F80 = 0x81 (fresh boot). The running
  firmware string now reads **"1019.1"** at data VA 0x245664 (confirmed: update worked, hook alive).
Not caught: the file location/size words (the cycle is too slow; F19B..F19E carried name bytes while sampled).
Next capture needs a faster watcher (F190/F198/F19B..F19E only, no per-read VCP flush once the monitor is known live).

### 1019.2 capture, 1020.0 failure, 1020.1 (2026-11-16)
- USB update to 1019.2 with the fast watcher: no F19x change was seen before DDC went silent (~41 s): during the load
  the SPARC stops serving DDC, so register sniffing cannot reveal the staging address. Static RE of segB: commands
  0x43 / 0x44 report XDATA 0x718 / 0x109 through F19B..F19E (values derived from FAT/LBA arithmetic, not a fixed DRAM
  address).
- **1020.0** put the slots in the dead code region (runtime 0x1E1A64): **code RAM ignores stores** (F0/F1 did not
  change ADDR, F2 kept reading the stale address; F3 on the stale unaligned ADDR trapped and DDC stalled until the
  monitor recovered on its own). Standard VCPs kept working.
- **1020.1** moves the slots to BSS 0xA803CFC0 (top of the largest unreferenced gap 0xA803C3E8..0xA803D000) and keeps
  the DRAM-port F6 window. F4 may write only the slots.
