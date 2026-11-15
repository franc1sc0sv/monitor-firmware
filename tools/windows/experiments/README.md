# Experiments (documented dead ends)

Kept for the record; not part of the supported workflow. See docs/adr/0012-isp-over-amd-adl.md.

| Folder | What | Result |
|---|---|---|
| `nvidia/` | Raw I2C through NvAPI on the NVIDIA GPU (DisplayPort) | The driver only allows addresses 0x37/0x50; MStar ISP (0x49) is refused. |
| `serdb/` | MStar serial-debug mode (I2C 0x59, "SERDB") to read RIU registers live | The chip answers, but reads over this ADL link return zeros or noise. No DRAM access. |
| `g5/` | First probes of the Odyssey G5 over its USB-C (HDMI adapter) link | ADL only returns EDID bytes and refuses writes; ISP needs a direct HDMI cable. |
