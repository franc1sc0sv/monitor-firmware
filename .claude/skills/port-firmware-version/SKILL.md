---
name: port-firmware-version
description: Port the patch to a new firmware version of a supported monitor. Use when mfw identify reports unknown firmware.
---
# port-firmware-version

Follow docs/guides/port-firmware-version.md. Key steps: unpack, import at 0x203800, locate every symbol of the known
version file by byte pattern, prove a cave unused (`RefsInRanges.java`), write `versions/<new>.toml` with guards
from the new dump, re-target and assemble the patch, check the listing, build, and run the HIL checklist before
marking it supported. Never assume the same RAM offsets.
