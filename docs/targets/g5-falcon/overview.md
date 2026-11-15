# Samsung Odyssey G5 "FALCON": current state

Second monitor. Unlike the LC34G55T (MStar MST9U, fully controlled), this is a **Novatek NT68500** platform and the
MStar patch/ISP tooling does not port. This page is the single source of truth for it; evidence trail is inline.
Confidence per ADR-0001.

| Item | Value | Conf |
|---|---|---|
| Panel / model | 32" 2560x1440 @ 165 Hz, 70x40 cm, made 2024 wk5; OSD model name `FALCON` | confirmed |
| Likely model code | Odyssey G5 G55C, `LS32CG552*`, firmware family `M-C5500GGZA-NNNN.N` | inferred (from G5 RE repo; label not yet read) |
| Scaler / CPU | Novatek NT68500 family; 8051 (boot/STBC/USB) + SPARC V8 BE main app | inferred |
| Flash | SPI NOR (boot table lists Macronix/Winbond/SST/ISSI JEDEC ids); exact part unknown | inferred |
| EDID product id | `0x7489` (DP) / `0x748A` (HDMI) | confirmed |
| Ports | DisplayPort → NVIDIA RTX 5080; single HDMI → AMD iGPU (gives raw ADL I2C). **Has a USB-A port** (firmware-update input). | confirmed (DP/HDMI); USB-A from user 2026-11-15 |
| Caps `cmds` | `01 02 03 07 0C E3 F3` — all standard MCCS (Get/Set/TimingReq/Save/CapsReply/CapsReq). **No vendor command opcode.** `E3`/`F3` are *not* vendor; they are the MCCS Capabilities Reply/Request. | confirmed |
| Caps `vcp` | `02 04 05 08 10 12 14(05 08 0B 0C) 16 18 1A 52 60(01 03 04 11 12 0F 10) 62 8D FF`, `mccs_ver(2.0)`, `asset_eep(32)`, `mpu_ver(01)` | confirmed (prior capture) |

## DDC/CI behaviour observed on hardware (2026-11-15)

- The G5 is on the **AMD iGPU HDMI** link (`[Amd]::Init()` → `name='Odyssey G5'`). **Confirmed.**
- Read-only 7-bit I2C scan ACKs only `0x30 0x37 0x3A 0x50 0x54`. No `0x49`/`0x59`: **not an MStar ISP target.**
  **Confirmed.**
- Get VCP `0x60` (input source) returns `0x06` (HDMI) over both ADL raw I2C and the OS dxva2 path. **Confirmed.**
- Get VCP `0x10 0x12 0x16 0xDF 0xC0 0xCA 0x8D` return no matching reply; OS `GetCapabilitiesStringLength` hangs on
  this display. **Confirmed.** Caps string above was captured in an earlier state. Hypothesis: full MCCS service
  needs the HDMI input to be the active/awake rendered source — retry when it is (open probe).
- Set VCP: only `0x60=0x06` (→ HDMI) confirmed to act; `0x09/0x0F/0x11/0x12` ignored (earlier session). **Confirmed.**

## Read-only tool

`tools/windows/novatek-isp-id.ps1` — identify the display on the ADL link, re-run the read-only scan, read standard
Get VCP (input source and the MCCS set), and report. No writes, no vendor opcode, no non-standard address.

## Flashing / control feasibility

See `docs/hardware/novatek-isp.md`. Two separate concerns, previously conflated:

- **Flash write transport (how bytes reach the SPI NOR).** Not over DDC: the MStar ISP slave is absent and no
  Novatek romcode-ISP entry over DDC is documented. The supported write path is the **USB `.img` updater**, and this
  unit **has a USB-A port**, so that path is available (confirmed-grade once the matching stock image is in hand).
  The G5 RE repo (`c8dhjp4tyv-bit/odyssey-g5-firmware-research`) shows the updater's integrity check is a whole-file
  16-bit byte-sum plus a strict `M-C5500GGZA-NNNN.N[XXXX].img` filename gate — both reproducible — so a *patched*
  image can be built and installed, as that project did (2-byte change) on the sibling `LS32CG552`. (inferred)
- **Runtime rich control (real input, events, memory) after patching.** Runs over HDMI/DP DDC/CI, like the LC34.
  "Unlocking HDMI communication" is therefore the *result* of a USB-flashed patch, not the flash transport.

The DDC-only `FE`/`EF` vendor escape (ASUS sibling) remains unconfirmed on the Samsung build and only writes
EEPROM/calibration/LUT via the live app; it is not a route to install a modified main image and is not on the plan.

### What already works today (read-only, standard DDC/CI)

- **Real input source** readable over VCP `0x60` — this is one of the LC34's headline features, already available on
  the G5 with no patch.

### What LC34-level control would require (and why it is blocked)

Patch points exist in the public G5 RE (SPARC main app: DDC/CI handler, Get/Set-VCP jump tables, event/OSD
dispatch, storage) — the analogues of the LC34 addresses in `docs/targets/lc34g55t/overview.md`. The NT68 reference
firmware has **no raw memory-read/write VCP, no menu-apply VCP and no simulate-keypress VCP** (confirmed in the ASUS
RE), so LC34-style features must be *added* by patching the SPARC app. The flash-write path for installing that
patch is the USB `.img` updater (see above).

### Recovery and risk

The USB updater is the recovery path, in place of an SPI dump: a patched build that fails to boot can be overwritten
by re-flashing the **stock `.img`** from USB — *provided the 8051 USB updater still runs* (it is not on the SPARC
patch path). Residual risk: a patch that also disables the updater or corrupts boot is a permanent brick
(open-case SOIC-8 recovery only), and the update UI was seen stuck at 1% for ~1 h before a normal reboot, so the
progress bar is not a reliable flash meter. Mitigation — staged flashing, never skip ahead:

1. Flash **stock, unmodified** by USB → proves the path works on this unit, sets a known baseline.
2. Flash a minimal **data-only** change (e.g. the proven 2-byte MGA/version edit) → proves re-flashing stock recovers.
3. Only then, **code patches** (real input report, event ring, memory read), one feature at a time, re-flashing
   stock between failures.

Flashing happens only with the user's explicit go-ahead in-session (`.claude/rules/flashing.md`), with a verified
stock image staged for recovery first.

## Plan (USB flashing route)

Blocking input needed from the user: the **exact model code** (rear label, `LS32CG5...`) and the **current firmware
version** (OSD → Support/Information). These pick the correct stock `.img`; flashing the wrong variant can brick.

1. Obtain the matching stock `M-C5500GGZA-*.img` (Samsung support download) and store two copies under
   `data/vendor/g5/` (gitignored). Offline, no hardware.
2. Implement the Novatek package tooling in `mfw`: whole-file 16-bit byte-sum, `M-C5500GGZA-NNNN.N[XXXX]` filename
   gate, record table parser. Round-trip test: re-emit the stock image byte-for-byte.
3. Build the first flashable artifact — stock re-wrapped unchanged — for the step-1 baseline flash.
4. Analyse the SPARC DDC/CI handler (Get/Set-VCP tables, event/OSD dispatch) against the public function catalogs;
   map LC34-feature analogues and a code-cave.
5. Create `firmware/targets/g5-falcon/{target.toml,versions/,patches/,listings/}`.
6. Staged flashing (see Recovery and risk), each step on explicit user go-ahead.

Read-only side probes (optional, not blocking): retry the full MCCS Get + OS caps with the HDMI input active/awake
to see if more of the DDC/CI surface opens up.
