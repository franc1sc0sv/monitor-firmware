---
name: build-image
description: Build a patched flash image from the user's own dump with mfw and report the flash range. Use before any flashing.
---
# build-image

1. `uv run mfw identify data/dumps/<dump>.bin` (stop if unknown: port the version first).
2. `uv run mfw build data/dumps/<dump>.bin --listing firmware/targets/<model>/listings/<version>/<file>.lst --out out/<name>.bin --engine zopfli`
3. `uv run mfw verify out/<name>.bin` must print OK.
4. Report: applied bytes, image SHA-256, changed sector count and the `-Start/-End` range for flash.ps1.
5. Never copy the image anywhere public. To flash, hand over to the `flash-monitor` skill.
