> **Research journal (historical).** Dated notes kept as evidence, including wrong turns. Sections before
> "Load address correction" use the superseded base 0x200000: add 0x3800 to those addresses. Current truth lives in
> `overview.md`, `settings-map.md` and `firmware/targets/lc34g55t/versions/1006.0.toml`. Where this journal says the
> switch fails after 5 s, the released v2.2+ uses 8 s.

# LC34G55T firmware reverse-engineering notes

Status legend: **confirmed** = verified against bytes, hardware or matching checksums; *inferred* = from decompiler output, not yet checked in disassembly or on hardware.

## Hardware access (confirmed)

- Scaler: MStar MST9U4. CPU of the main app: MStar AEON R2 (`./cpu/risc32/MST9U`).
- SPI flash: Winbond W25Q64 (JEDEC `EF 40 17`, 8 MB).
- MStar ISP (I2C 0x49) answers over **HDMI through the AMD iGPU** (ADL `ADL2_Display_DDCBlockAccess_Get`). NVIDIA NvAPI refuses every I2C address except 0x37/0x50/0x30.
- ISP read: write `10 03 a2 a1 a0`, write `11`, read from 0x93, write `12`. Enter `MSTAR`, exit `24`. ~10 KB/s.

## Flash layout of firmware 1012.1 (confirmed)

| Region | Range | Notes |
|---|---|---|
| PM 8051 | `0x000000–0x010000` | |
| AP load descriptor | `0x011000` | u32 LE: ap_flash_start `0x31080`, ap_ram_start `0x200000`, ap_ram_end `0x33026f`, ap_flash_end `0x1612ef`, 0, **CRC-32 `0xcc46fd9b`** over `[0x31080,0x1612ef)`, 0, 0, filesize-4 `0x2cc048`, `0x11000` |
| Config A / B | `0x10000`, `0x20000` | DDC/CI capabilities string at `0x13751` and `0x23751` |
| AP prefix | `0x31080–0x34880` | uncompressed, image info header (magic `55AA5678`) at `0x32180`, model `L-QMD55MWWAC-3333`, AP length `0x13026f` at +0x4a |
| AP DEFLATE | `0x34880–0x1612e9` | raw deflate (zlib wbits -15) → `0x2c19b8` bytes, load at `0x200000` |
| AP size + check | `0x1612e9` | u32 LE `0x2c19b8`, then u16 `0xac3a` (**algorithm not identified yet**: not CRC-16/CCITT-FALSE/XMODEM/KERMIT/X25/ARC/MODBUS over the obvious ranges) |
| File trailer | EOF-16 | `55 AA AB CD`, **CRC-32 `0xe0ad000b`** (poly 0x04C11DB7, MSB-first, init 0, no xorout, stored BE) over all but the last 4 bytes |

CRC-32 algorithm and the MST9U container format match joshado/s718ql-firmware-patch (docs/firmware-components.md §1).

## DDC/CI code (inferred from decompiler)

- Ghidra 12.1.3 + eb4x/ghidra-plugin-aeon v0.1.0, language `AEON:BE:32:R2`, base `0x200000`. Seeding: from `0x208800`, `b.addi r1,r1,…` prologues, then every in-range LE pointer → 4747 functions.
- **Set VCP dispatcher `FUN_0026d6ff`**: VCP code in `DAT_004c4e2c`, value low byte `DAT_004c4e36`, high byte `DAT_004c4e37`. Unsupported/invalid → `DAT_004c4e2d=0xff`, `DAT_004cc61e=1`.
  - `0x60` input source accepts **Samsung values 3, 6, 9** only (not MCCS 0x0F/0x11/0x12): 9 → `DAT_004d00e3=1`, 6 → `=2`, 3 → leaves `DAT_004d00e3` unchanged (check in disassembly). Then `FUN_0026accf` → `FUN_0026abf1(DAT_004d00e3)`.
  - `0x10` brightness clamps to 100 → `DAT_002041d3`, `FUN_002801ba`.
  - `0xD6` power: 4 → sets bit 2 of `DAT_004c4e1c`… `FUN_0026c1ad`.
  - `0xE6`=1 → `FUN_0028ad7b(0x12)`; `0xE7` vendor sub-commands.
- **Input switch `FUN_0026abf1(sel)`**: `cfg = *(DAT_003c61f0)`; `cfg[0xde]=sel`; sel 1→port 0, 2→port 1, 3→port 2; calls `FUN_00247de9(cfg[0xe4], port)`; stores port at `cfg[0xe5 + cfg[0xe4]]`. `cfg[0xe4]` looks like the window index.
- Live monitor reports Get VCP 0x60 = `0x09` while on DisplayPort, consistent with 9 = port 0 = DP.
- VCP code table at `0x3dad61` (−1 terminated) with per-code tables at `0x3dad74` and `0x3dad87`; zero in the image, so filled at runtime or in a separate data space.
- Get VCP reply builder: not located yet. Functions around `0x26c860–0x26cbf9` touch the reply fields but Ghidra splits them (unaffected registers): fix function boundaries there first.

## DDC/CI command path (2026-11-15)

Addresses as `1012.1 / 1006.0 (installed)`.

- Per-port DDC slave ISR: `FUN_00217118(port)` (1012.1). RX bytes go to `0x4ef978[]`. When a full
  message arrives it sets `DAT_004c4cfb = 5` (pending) and `DAT_004c4ce8 = FUN_0020eaf3(port+4)`, the
  logical port index (0..3) **the message arrived on**. The 1006.0 equivalent of `ce8` is `0x4c19d0`.
- Main loop `FUN_0020f7c6`: if pending == 5 it calls `FUN_0020f6a5` (same address in both versions).
- `FUN_0020f6a5` calls the parser `FUN_0026da61 / 0x26d6b3`, which dispatches on the opcode
  (`0x4ef979`): 0x01 Get VCP -> `0x26c7a9 / 0x26c41c`; 0x03 Set VCP -> `0x26d6f3`; 0x07 timing report;
  0xF3 capabilities (gated by the port-struct flags at `0x3c5484 + port*0x8c`); 0xCx Samsung/factory.
- Reply buffer `0x4ef978`: `88 02 RC VCP TP MH ML CH CL`, built from `4e37/4e36/4e30/4e2d`
  (1012.1) = `1b1f/1b1e/1b18/1b15` (1006.0).
- Get VCP: a jump table indexed by the VCP code; the decoded table pointer (`0x377b30` / `0x377410`)
  does not look valid. The Ghidra AEON plugin also fails to decode instructions around `0x26c8c0`, which
  is why the case blocks show up as bad functions.
- **Get 0x60 case** (`0x26c828 / 0x26c49b`): max = 0x0E; current = 9 when `ce8 == 0`, the case at
  `0x26cc9c / 0x26c90c` when `ce8 == 1`, and 0x0A when `ce8 == 2`.
  **The firmware reports the port the query came in on, not the input on screen.** It never reads the
  real active input (`cfg[0xde]` / `cfg[0xe5+...]`, which the input-switch routine writes).
- Live HDMI test (inactive port, the Mac or nothing on screen): every Get returns RC = 01 (unsupported),
  even 0x10 brightness, and Sets 3/6/9/0x0F/0x11/0x12/1/2/5 show no visible effect on the link.

## Load address correction and DDC path in 1006.0 (2026-11-15, later)

- The decompressed AP runs at **0x203800**, not 0x200000. Evidence: with LE pointers, 517 string
  pointers hit at 0x203800 vs 29 at 0x200000, and Get VCP jump-table entries land exactly on the case
  blocks (0x60 -> the instruction right after `jr`, default -> the unsupported block). Old Ghidra
  addresses = real - 0x3800. Data pointers are little-endian.
- New project `data/ghidra2/inst` (1006.0 at 0x203800): 9124 functions, decompile in `data/ghidra2/inst.c`.
- Real addresses (1006.0):
  - main loop `0x26b4f9`; it calls the DDC service `0x212fc6` on every iteration, with no input gating;
  - DDC2Bi ISR `0x2126dd(hwport)`, dispatched from `0x212c6f` for HW ports 6, 0 and 1 (regs `0x7c20/24/25`);
  - DP-AUX MCCS ISR `0x21a8df(port)`, dispatched from `0x21ac40` / `0x215f9f` for ports 0..2 when bit n of `0x4c9b16` is set;
  - RX/TX buffer `0x4ec618`, pending flag `0x4c19e3`, source logical port `0x4c19d0` (= `0x2122f3(hwport)`);
  - processor `0x212ea5`, parser `0x270eb3`, Get VCP `0x26fc1c`, Get 0x60 case `0x26fc9b`, Set handler `0x270b45`;
  - Get VCP jump table `0x377410` (LE u32, 255 entries).
- HDMI DDC/CI engine enable: regs `0x7c18/0x7c19` = 0xB7 when `cfg[0xd7] & 0x40`. `0x28c472` / `0x28c5ba`
  clear them only temporarily while reloading EDID.
- On the inactive HDMI the reads behave like a free-running TX stream that never resets. The
  "88 02 01 10 01 FF FF 00 00" replies (RC=1 for brightness) cannot come from the 1006.0 Get handler,
  where 0x10 is supported. So requests on the inactive port are most likely never processed.
- SERDB (I2C 0x59) answers, but reads return zeros or noise with this ADL link. Sequence from
  linux-chenxing: `SERDB`, then `81 83 84 53 7F 35 71`, then `10 a3 a2 a1 a0` followed by a read; exit `34 45`.

## v1 flashed and verified (2026-11-15)

- Boot chain: stage1 at flash 0x2000 (AEON, runs from flash at 0) picks the image bank (0 or 0x400000) and BDMA-copies
  stage2 (flash 0x67cd, 0x4ebc bytes) to 0x1000100. Stage2 copies the 0x3800 prefix and inflates the raw DEFLATE AP,
  then jumps to 0x200100. **No check of the u16 or the CRCs at boot.** prefix+0x114a holds the region length
  (prefix + stream + 6) and must be updated.
- The CPU reads 32-bit data **little-endian** (jump tables, pointers); the Ghidra plugin decodes data as BE.
  cfg pointer at 0x3c41b0 = 0x00204000 (settings RAM, zero in the image).
- Memory map: .text 0x20c000..0x39a000 (0x2aa52b call); BSS 0x4c1ea0..0x4fe6b0 (cleared at entry); heap afterwards.
  Free code cave: 0x399817..0x39a000 (end-of-.text padding, 2025 bytes, no references).
- Tools: `tools/re/AsmPatch.java` (Ghidra SLEIGH assembler; picks only encodings seen in the original),
  `tools/fwbuild.py` (round-trips the original byte-identically, then repacks), `tools/windows/amd-flash.ps1`
  (erase/program/verify per 4 KB sector, 3 retries; SR1=0x00, no block protection).
- Write test on scratch sector 0x7FF000 OK. v1 flash: 303 sectors written and verified, 584 s.
- **Result:** after Set 0x60=9 sent over HDMI, Get 0x60 over HDMI returns 0x09 and over DP 0x09. Stock returned
  06 over HDMI and 09 over DP at the same moment. Switching back gives 06.

## v2 event log (2026-11-15)

Source: `patches/v2-events.s` (includes v1). Assembler `tools/re/AsmPatch2.java` (labels, multi-pass; branches to
labels always use the longest form so layout converges; fails on non-convergence). Independent listing checker
`tools/verify_listing.py` (contiguity, every branch target is an instruction start, text round-trip). Every
instruction form used also occurs in the stock compiler output (`tools/re/MnemLens.java`).

- RAM: 1 KB at 0x4fe6b0, reserved by moving the sbrk base (word at 0x4c1390) and the BSS-clear bound (prefix 0x2001a7,
  `ori r4,r4,0xeab0`), so the block is zero on every boot.
- Clock: u16 at 0x4cea40, +1 every 10 ms in the 1 ms timer ISR 0x24d72d; extended to 32 bits by the poller.
- Hooks: main loop 0x26b6d3 (`jal poll`, which calls the stock DDC service 0x212fc6 first); Set dispatch 0x27123d
  (`jal sethook`, tail-calls stock 0x270b45); Get table entries 0xEA..0xEF (0x3777b8..0x3777cc, LE pointers).
- Power: cfg[0xd7] bit0 = power on (cleared by power-off 0x26f620); bit 0x40 = DDC/CI enabled.
- Watches: input port, cfg[0xde], cfg[0xd7], low byte 0x4ca78c, active-port struct +0x1c, hfreq != 0,
  low byte 0x4cebe4, 0x4ec92d. DDC 0x60 requests start a pending verdict: done (0x11) or failed after 5 s (0x12).
- Image: zopfli raw DEFLATE gives 27 KB headroom; the decompressed RAM image differs from stock in 927 bytes.
- Client: `client/` (Python, no dependencies): Windows dxva2, Linux i2c-dev, macOS IOAVService (untested).
  `tools/windows/events.ps1` is the PowerShell test reader over ADL.

## v3.1 full access (2026-11-15)

Source `patches/v3-full.s` (includes v1 + v2.2). Flashed and verified.
- RAM block grown to 2 KB (0x4fe6b0..0x4feeb0; BSS bound `ori r4,r4,0xeeb0`, sbrk base 0x4feeb0).
- Set 0xF0/0xF1 = address high/low; Get 0xF2 = 4 bytes at the address (only 0x200000..0x7fffff), auto +4.
- Set 0xF4 = write one byte, only 0x204000..0x2043ff (settings), auto +1. Set 0xF6 = apply menu item 0..0x6e via
  0x284884(item, 1), the same call the stock DDC path uses (applies and saves).
- Settings scanner: 0x204000..0x2041ff vs shadow (EV+0x400), 8 bytes per main-loop pass, mask at EV+0x600.
  Event 0x20 | offset>>8, old = offset low byte, new = value. (v3.0 bug: w8 jumped past the scanner; fixed in v3.1.)
- Menu engine: apply table 0x378810 (items 0..0x6e, 64 items use the generic path), DDC set-item table 0x377878
  (items 4..0x46). Generic VCP->item table at 0x3d8d21 (codes), +0x13 item ids, +0x26 max values.
- Mapped variables: brightness 0x2041d3 (item 0x0d), contrast 0x2041da (0x0e), sharpness 0x2041df (0x0f),
  R/G/B 0x2041d7/d8/d9 (0x11/0x12/0x13), VCP F7 0x2041d6 (0x31), VCP F3 0x2041e0 (0x04).
  Model string at 0x204089 ("LC34G55TWWNXZA"), serial at 0x20409b. Per-picture-mode blocks repeat from ~0x2041c0.
- Verified: poke 0x2041d3 + apply 0x0d changes brightness; every DDC brightness/contrast change logs a
  setting event with its exact address. Settings restored afterwards (brightness 99, contrast 85).
- Stock factory opcodes in the parser: 0xC2 (write factory blocks 0x2040c1/0x2040ce), 0xC3 (factory read),
  0xC4 (EDID/serial write), 0xCB/0xCC (serial read). Not used by us.

## Inactive HDMI DDC/CI, static pass (2026-11-20)

Full note: `inactive-hdmi-ddc.md`. No hardware touched.
- Followed IRQ `0x6E` from attach (`0x24dba9`) through the handler `0x24d65c`, the DDC2Bi dispatcher `0x212c6f`, the
  ISR `0x2126dd`, the service/processor/parser and the reply writer `0x212d39`. None of them reads the active input.
  The HDMI engine's enable and masks are written only at init (`0x2130d8`) and around EDID reloads; the input switch
  never touches them; HPD/termination drop only as timed pulses on the port being selected.
- HDMI = DDC2Bi HW port 1 (port table entry 1, DDC id 2). HW ports 6 and 0 are not wired on this model.
- The 2026-11-15 reply `88 02 01 10 01 FF FF 00 00` has TP = 1; the Get handler sets TP = 0 for codes above `0x0F`
  and answers `0x10` with RC = 0, so that reply was not built by the AP. Still consistent with "never processed".
- DP and HDMI share the request buffer, pending flag and reply length: concurrent hosts can get each other's replies.
- Next: the read-only peek experiment in the note (ISR-only fields `0x4c19ce`, `0x4c19d2`, `0x4c19d8`, `0x4c19da`,
  `0x4c19dc`, `0x4c92fd`).
