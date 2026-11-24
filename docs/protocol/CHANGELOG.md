# Protocol changelog

| Firmware | Protocol | Client | Change |
|---|---|---|---|
| v1 | - | - | Get 0x60 reports the input on screen |
| v2 / v2.1 / v2.2 | 2 | 0.2.0 | Event log 0xEA..0xEF; own 10 ms clock (v2.1); switch verdict requires a locked picture (v2.2) |
| v3 / v3.1 | 2 | 0.3.0 | Memory read 0xF0..0xF2, settings write 0xF4, menu apply 0xF6, setting-changed events (scanner fixed in v3.1). Version byte was not bumped (additive). |
| v3.2 (LC34), p3 (G5) | 3 | crate 0.2 | Capability word 0xE8, truthful Get 0xD6, soft standby (Set 0xD6 = 4/1, 5 = real off), switch guard, events 0x14 power-state and 0x15 cable-mask. Specified 2026-11-23, not yet flashed |
