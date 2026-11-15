# Flash an image

> Flashing can permanently disable the monitor. Recovery may need opening it and an external SPI programmer.
> You need a verified backup of **this** monitor first (`dump.md`).

```powershell
cd tools\windows
.\flash.ps1 -Mode test                            # scratch sector 0x7FF000: write, verify, erase
.\flash.ps1 -Mode write -Image C:\...\lc34-v3.1.bin -Backup C:\...\LC34G55T-full-1.bin `
            -Start 11000 -End 2c0000 -Log C:\...\flash.log
```

The script refuses the boot area (below `0x11000`), checks the image equals the backup outside the range, writes only
sectors that differ, verifies each one, and logs the SHA-256 of both files. On failure it exits with code 1 and does
**not** reset the monitor (it stays in ISP mode) and prints the restore command. After success the monitor reboots;
check with `uv run monitor-events status` (expects the event log) and the HIL checklist.
