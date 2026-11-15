# ADR-0012: Flash access: MStar ISP over AMD ADL on HDMI

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

MStar ISP lives at I2C 0x49 on the DDC bus. NVIDIA NvAPI only allows 0x37/0x50. MStar serial debug (SERDB, 0x59) answers but returns zeros/noise on this link. AMD ADL `DDCBlockAccess` allows arbitrary I2C on the iGPU's HDMI port.

## Decision

Read and write the SPI flash through ADL on the AMD iGPU's HDMI port, using the flashrom mstarddc_spi protocol facts (MSTAR, 0x10 write, 0x11 read, 0x12 end, 0x24 reset). NVIDIA and SERDB attempts are archived in `tools/windows/experiments/`.

## Consequences

Development needs a Windows PC with an AMD GPU (iGPU) on HDMI. ISP is hardware-level, so a broken AP can still be re-flashed (stock was restored once this way).
