# Novatek NT68500 programming paths (Odyssey G5 "FALCON")

How the second monitor's scaler can and cannot be read/written, and why the MStar ISP tooling
(`docs/hardware/mstar-isp.md`) does not apply. Confidence labels per ADR-0001: **confirmed** = bytes / hash /
hardware observation in *this* setup; **inferred** = from the public reverse-engineering of sibling Novatek units,
not yet reproduced on our hardware.

## Platform

- Scaler: Novatek NT68500 family (same family as the ASUS PG42UQ's NT68552). Two 8051 cores (boot / STBC /
  USB-updater roles) plus a SPARC V8 big-endian main application. **Inferred** for our unit from the EDID, caps
  string and the public G5 research; the MStar MST9U assumptions of this repo do not hold.
- No MStar ISP slave. A full read-only 7-bit scan on the AMD-ADL HDMI link ACKs only `0x30 0x37 0x3A 0x50 0x54`.
  `0x49` (MStar "MSTAR" ISP) and `0x59` (MStar SERDB) never ACK, with HDMI selected and active. **Confirmed**
  (2026-11-15). So `AmdIsp` / `tools/windows/MonitorTools/AmdFlash.cs` cannot touch this scaler.
  - `0x30`/`0x37` = DDC/CI (MCCS), `0x50` = EDID block 0, `0x54` = EDID extension / E-DDC segment. `0x3A` is a
    companion/secondary DDC address (unidentified). None is a flash ISP port. **Confirmed** addresses,
    **inferred** roles.

## What addresses answer, and how little

Over AMD ADL raw I2C *and* over the OS DDC/CI API (dxva2), the G5 currently answers **only** Get VCP `0x60`
(input source = `0x06` HDMI). Get VCP `0x10` (brightness), `0x12`, `0x16`, `0xDF` (MCCS version), `0xC0`, `0xCA`,
`0x8D` return no matching reply, and the OS `GetCapabilitiesStringLength` call **hangs** on this display.
**Confirmed** (2026-11-15). Set VCP `0x60=0x06` (switch to HDMI) is the only write confirmed to act (earlier
session). The advertised caps string lists `vcp(… 10 12 14 … 60 62 8D FF)`, so the handler *should* support more;
the gap is unexplained. Most likely the HDMI input must be the **active, awake, rendered** source for the SPARC
app to service the full MCCS surface — a probe condition to retry, not a proven limitation.

## Novatek flash-write paths (none is DDC-only on our unit)

| Path | Mechanism | Reachable here? |
|---|---|---|
| USB `.img` updater | 8051 record-2 USB host stages the file; `CMD_LOADFILE2DRAM`, `CMD_START_ISP_ROMCODE_MODE`, whole-file `sum16` check, model/version filename gate (`M-C5500GGZA-NNNN.N`). | **No** — the user's G5 has no USB port. **Confirmed** no USB; mechanism **inferred** from G5 research. |
| ROMCODE ISP (`CMD_START_ISP_ROMCODE_MODE[_DUALFW]`) | Boot/USB-updater 8051 enters a bootROM programming mode. | Driven from the USB updater, not DDC. **No evidence of a DDC entry sequence** on Novatek NT68500. **Inferred.** |
| Vendor DDC escape `FE` / `EF` | In the sibling ASUS NT68552 firmware, hidden VCP `FE` is a multi-byte service channel; sub-command `EF` reads/writes 32-byte EEPROM/LUT blocks, `E1 A1` is an update/reboot entry, `F1` writes calibration EEPROM. All on the standard `0x37` DDC/CI address, no separate slave. | **Unknown on the G5.** `FE` is not in our caps string (it is hidden in ASUS too), and we have not confirmed Samsung's build implements it. Even if present, it writes **EEPROM/calibration/LUT regions via the live app, not a full-chip SPI erase/program** — it cannot install a modified main image. **Inferred** from `docs` of the ASUS PG42UQ RE. |
| External SPI (SOIC-8 clip / CH341A) | Direct to the W25Q-class flash on the board. | Out of scope — user will not buy a programmer. |

### Why there is no "enter ISP / read JEDEC / exit" to propose

On MStar the ISP is a distinct I2C slave (`0x49`) that answers independently of the firmware, so a read-only
JEDEC-ID probe exists. On Novatek NT68500 **no such DDC slave appears** (scan is clean), and no public source
(flashrom, awto-ddc, the ASUS and G5 RE repos) documents a Novatek DDC romcode-ISP entry. The Novatek factory
programmer is a USB device (Cypress-based "Postal2"-style) or an SPI clip, not a DDC magic write. So there is **no
documented read-only ISP sequence to run**, and none is proposed.

## Sources (public, read as data)

- ASUS PG42UQ (NT68552) RE: `github.com/schlarpc/asus-pg42uq-firmware-re` — `ddc_surface.md` (DDC frame on `0x37`,
  full VCP table, hidden `FE` service escape with `EF` EEPROM/flash block R/W, `E1 A1` update entry), `usb_surface.md`.
- Odyssey G5 (LS32CG552 / M-C5500GGZA-1010.0) RE: `github.com/c8dhjp4tyv-bit/odyssey-g5-firmware-research` —
  `docs/UPDATE_PIPELINE.md`, `docs/PROCESSORS_AND_BOOT.md`, `docs/HARDWARE_MAP.md`.
- flashrom `mstarddc_spi` (MStar only), `github.com/awto-au/awto-ddc` (Realtek RTD ISP over DDC at `0x4A`) — shown
  only to establish that a DDC ISP needs a vendor-specific slave/sequence we do not have for Novatek.
