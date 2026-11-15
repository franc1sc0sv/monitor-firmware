---
name: map-setting
description: Identify which settings byte an OSD menu option uses, from the firmware's setting-changed events, and record it. Use when mapping monitor settings.
---
# map-setting

1. Start the API (`uv run monitor-events serve` on the Windows side) or use `monitor-events watch`.
2. Ask the user to change exactly one OSD option and say which (name, old -> new value).
3. Read the new `setting-changed` events (`/api/events?since=<seq>`): offset = ((id & 1) << 8) | old, value = new.
   Ignore known noise (boot counter 0x0c6, powersave-flags).
4. Find the menu item: search the apply table (`0x378810`) / set-item table (`0x377878`) or test `apply` with the
   candidate item after restoring the value. Record the range (min/max) from the OSD.
5. Add the row to `docs/targets/<model>/settings-map.md` and `SETTING_NAMES`/`SETTING_ITEMS` in
   `client/src/monitor_events/protocol.py`; add a test if behaviour is non-trivial.
6. Restore the user's original value.
