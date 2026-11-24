# Samsung LC34G55T: current state

Single source of current truth for this monitor. The dated research trail (including superseded addresses) is
`journal.md`; prefer this page and `firmware/targets/lc34g55t/versions/1006.0.toml`.

| Item | Value |
|---|---|
| Panel / model | 34" 3440x1440, LC34G55TWWNXZA |
| Scaler / CPU / flash | MStar MST9U, AEON R2, Winbond W25Q64 8 MB |
| Installed firmware | M-T5534GCPA-1006.0 (AP sha256 `0ca44b68…`) |
| Downloadable firmware | 1012.1 (Samsung site, `M-T5534GCPA.zip`): different addresses, not ported |
| Ports | 0 = DisplayPort (VCP 0x60 `0x09`), 1 = HDMI (`0x06`) |
| Patched release on the unit | v3.1 (protocol 2), flashed and verified 2026-11-15 |

## Key addresses (1006.0, real RAM addresses)

| What | Address |
|---|---|
| Main loop / DDC service call | `0x26b4f9` / `jal 0x212fc6` at `0x26b6d3` |
| DDC2Bi ISR (HDMI/DP DDC engines, HW ports 6/0/1) | `0x2126dd`, dispatched from `0x212c6f` |
| DDC processor / parser | `0x212ea5` / `0x270eb3` |
| Get VCP handler / jump table / common reply tail | `0x26fc1c` / `0x377410` (LE, 255 entries) / `0x26fcd3` |
| Set VCP handler / dispatch call | `0x270b45` / `0x27123d` |
| Input switch routine | `0x26e064` (`cfg[0xde]` = selection, `cfg[0xe5 + cfg[0xe4]]` = port) |
| Menu engine: apply item / DDC set-item table / VCP-to-item table | `0x284884` / `0x377878` / `0x3d8d21` |
| 1 ms timer ISR (tail call at `0x24d885`) | `0x24d72d` |
| cfg pointer (-> `0x204000` settings RAM) | `0x3c41b0` |
| Port structs (stride 0x8c; +0x1c sync flags, +0x22 h-freq) | `0x3c3440` |
| Code cave / RAM block | `0x399820..0x39a000` / `0x4fe6b0..0x4feeb0` |

## Behaviour worth knowing

- Stock Get 0x60 reported the queried port (fixed by v1). All inputs answer DDC/CI when their source is connected.
- Energy cap (stock, US models "XZA"): when `0x2041d6` (VCP F7 / menu item 0x31) is non-zero and an adaptive-sync
  condition holds, the backlight is pinned to `0x2041c2` (52, from `0x2802f3`) and brightness is ignored. Writing
  VCP F7 = 1 clears it. Seen once during testing; it looked like "dull picture, brightness does nothing".
- Power (hardware, 2026-11-23, Windows over NVIDIA DP, v3.1): Set 0xD6 = 4 puts the monitor in standby (LED on) and
  the DP link drops at once: Windows lists one monitor fewer, every Get fails and Set 0xD6 = 1 has no handle to go
  to. Waking took the power button (it came back on HDMI and the Mac re-arranged its displays). **Confirmed.** So
  "power on by command" is not possible from the DP host with the current firmware; open routes: a video signal, a
  DDC request from the HDMI host while in standby (untested), or a patch (Tandem plan, Phase C).
- **Hang on display sleep (hardware, 2026-11-23, v3.1, seen once):** the PC sent `SC_MONITORPOWER 2` (all displays
  off). The monitor went dark with **no LED**, stopped answering DDC, ignored the power button and real mouse/keyboard
  wake, while Windows kept listing it (EDID still readable). Only unplugging the power cable for 30 s recovered it.
  Not yet reproduced, not yet compared with stock. HIL item "Standby and wake" was never run before.
- The DP link re-trains once right after the monitor boots: Windows drops it for ~3 s about 3 s after it first
  appears. **Confirmed** (2026-11-23).
- Stock Get 0xD6 is unreliable: it mostly returns the previous request's reply (stale buffer), once `0xD8/0x02`.
  Use the power flags in 0xEE instead. **Confirmed** (2026-11-23, eight reads interleaved with other codes).
- Capabilities (stock, unchanged by the patch): `60( 12 0F 10)` and `D6(01 04 05)`, although the firmware's real
  0x60 values are the Samsung `0x09`/`0x06`/`0x03`. **Confirmed.**
- Stock factory opcodes exist in the parser (`0xC2` factory blocks, `0xC4` EDID/serial write, `0xCB/0xCC`): never used.

See `settings-map.md` for the settings block.
