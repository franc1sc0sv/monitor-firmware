---
name: flash-monitor
description: Flash a built image to the monitor over MStar ISP with all safety checks, then smoke-test. Use only after the user explicitly approves flashing in this session.
---
# flash-monitor

Stop and ask the user if any check fails. Never improvise around a failure.

1. Confirm the user approved this specific flash in the current session (image name and what it changes).
2. Pre-flight: backup exists, two dumps had equal SHA-256; `mfw verify` on the image is OK; the range comes from
   `mfw build`; the monitor's HDMI is on the AMD iGPU and detected (`tools/windows/diag.ps1`).
3. Copy image and backup to a Windows path (e.g. `%TEMP%`), compare SHA-256 after copying.
4. `.\flash.ps1 -Mode test`, then
   `.\flash.ps1 -Mode write -Image <img> -Backup <backup> -Start <s> -End <e> -Log <log>` (run in background; ~10 min).
5. If it exits non-zero: do not power-cycle; run the `restore-stock` skill immediately.
6. After success wait ~20 s, then `uv run monitor-events status` (or `tools/windows/events.ps1`) and ask the user to
   confirm the picture and a visible brightness change (`tools/windows/hil/dark.ps1`).
7. Record the result (log path, hashes) in the session summary; update docs/roadmap.md if a release changed.
