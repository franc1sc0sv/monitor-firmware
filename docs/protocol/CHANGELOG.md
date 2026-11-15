# Protocol changelog

| Firmware | Protocol | Client | Change |
|---|---|---|---|
| v1 | - | - | Get 0x60 reports the input on screen |
| v2 / v2.1 / v2.2 | 2 | 0.2.0 | Event log 0xEA..0xEF; own 10 ms clock (v2.1); switch verdict requires a locked picture (v2.2) |
| v3 / v3.1 | 2 | 0.3.0 | Memory read 0xF0..0xF2, settings write 0xF4, menu apply 0xF6, setting-changed events (scanner fixed in v3.1). Version byte was not bumped (additive). |
