# Dump the flash (backup)

Needs: Windows, the monitor's HDMI connected to an **AMD** GPU (the iGPU works), and that HDMI being the monitor's
active input or at least detected by the AMD driver. Run from PowerShell (or from WSL through `powershell.exe`).

```powershell
cd tools\windows
.\isp-id.ps1                                  # expect JEDEC EF 40 17; the monitor resets afterwards
.\dump.ps1 -Out C:\path\LC34G55T-full-1.bin   # ~14 minutes for 8 MB
.\dump.ps1 -Out C:\path\LC34G55T-full-2.bin
```

Compare the two SHA-256 values printed: they must be equal. Keep the backup in `data/dumps/` (ignored by git) and a
copy on reliable storage. The dump contains your serial number: never publish it.
Then: `uv run mfw identify data/dumps/LC34G55T-full-1.bin`.
