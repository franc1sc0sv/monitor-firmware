---
name: restore-stock
description: Write the verified stock backup back to the monitor. Use after a failed flash or when the user wants the original firmware.
---
# restore-stock

1. Locate the verified backup (`data/dumps/*-full-1.bin`) and confirm its SHA-256 equals the second dump.
2. Copy to a Windows path and re-check the hash.
3. `.\flash.ps1 -Mode write -Image <backup> -Backup <backup> -Start 11000 -End 2c0000 -Log <log>`.
4. If ISP does not answer (no JEDEC id): ask the user to power-cycle the monitor, retry. Last resort is an external
   SPI programmer (docs/guides/recover.md).
5. Verify: `monitor-events status` must report "VCP 0xEA unsupported" (stock), picture normal, brightness responds.
