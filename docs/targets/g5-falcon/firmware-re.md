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
- `0x15E560(byte)` = send one SPI byte (writes data reg 0x14 via HAL 0xA002EF00, triggers reg 0x13).
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
