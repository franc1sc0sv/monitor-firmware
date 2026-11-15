---
name: hil-check
description: Walk the hardware-in-the-loop checklist after flashing a firmware release and record results. Use before tagging a release.
---
# hil-check

Go through docs/guides/hil-checklist.md item by item. Use `tools/windows/hil/*.ps1` (cycle, clock, dark, blink) and
the client (`status`, `history`, `switch`). Items that need eyes (picture, brightness visibly changing, OSD) must be
confirmed by the user, not inferred from read-back values. Write the results into the release notes / CHANGELOG.
