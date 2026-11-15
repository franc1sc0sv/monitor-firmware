---
paths:
  - "tools/windows/**"
---
# Flashing rules

- Flash only with the user's explicit go-ahead in the current session, via the `flash-monitor` skill.
- Before writing: two equal dumps, `mfw build` and `mfw verify` clean, `flash.ps1 -Mode test` passes.
- Never write below 0x11000 (`-AllowBoot` is for documented recovery only). Range comes from `mfw build` output.
- On failure the monitor stays in ISP mode: write the backup back immediately (`restore-stock` skill).
- After success: `monitor-events status` must show the event log; then the HIL checklist.
- Ask the user to confirm what they *see* on screen (brightness test) — reading values back is not enough.
