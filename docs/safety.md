# Safety

- Flashing can permanently disable the monitor. Recovery may need opening it and an external SPI programmer.
  Warranty is likely void.
- Tested on one unit: LC34G55T, firmware 1006.0, W25Q64 flash, AMD iGPU over HDMI, Windows 11.
- Always dump twice and compare hashes before any write. Keep the backup off unreliable storage.
- The tools refuse: unknown firmware versions, patch sites whose stock bytes differ, writes below `0x11000`,
  images that differ from your backup outside the write range. After a failed write they do not reset the monitor.
- The patch does not touch backlight drive, panel power sequencing or voltages, and the public interface cannot write
  outside the settings block.
- Known unknowns: the u16 check word after the AP stream is copied unchanged (boot ignores it); Samsung's own
  updater behaviour on a patched unit is untested.
- The patched firmware lets any connected host read RAM and change settings (see SECURITY.md).
