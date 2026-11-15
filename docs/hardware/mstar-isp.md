# MStar ISP over DDC

The scaler answers an in-system-programming protocol on the monitor's DDC bus, independent of the running firmware.
Protocol facts from flashrom's `mstarddc_spi` (GPL-2.0; facts only, no code copied).

| Step | I2C write to 0x49 (8-bit 0x92) |
|---|---|
| Enter ISP | `"MSTAR"` |
| SPI bytes, chip select low | `0x10` + bytes (several writes may follow inside one transaction) |
| Read | `0x11`, then read N bytes from 0x93 |
| End transaction (CS high) | `0x12` |
| Leave ISP (reset the scaler) | `0x24` |

SPI commands used: `0x9F` JEDEC id (expect `EF 40 17`), `0x05/0x35/0x15` status registers (SR1 was 0x00: no block
protection), `0x06` write enable, `0x20` 4 KB erase, `0x02` page program (256 bytes, sent as 32-byte chunks),
`0x03` read. Implementation: `tools/windows/MonitorTools/AmdI2c.cs` (`AmdIsp`) and `AmdFlash.cs`.

Transport: AMD ADL `ADL2_Display_DDCBlockAccess_Get` on the iGPU's HDMI port (any address allowed). NVIDIA NvAPI
only allows 0x37/0x50. MStar serial debug (0x59, `SERDB`) answers but gives zeros/noise on this link. ISP reads
8 MB in about 14 minutes; writing the AP region takes about 10 minutes.
