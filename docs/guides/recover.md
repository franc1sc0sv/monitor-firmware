# Recover

Restore the stock firmware from your verified backup (done once on 2026-11-15, 594 s, booted normally):

```powershell
.\flash.ps1 -Mode write -Image C:\...\LC34G55T-full-1.bin -Backup C:\...\LC34G55T-full-1.bin -Start 11000 -End 2c0000
```

ISP is implemented in the scaler hardware, so it answered even with a modified AP. If ISP stops answering
(no JEDEC id), power-cycle the monitor and retry. Last resort: open the monitor, clip the W25Q64 (SOIC-8) with an
external programmer and write the backup (not needed so far; board location not yet documented).
