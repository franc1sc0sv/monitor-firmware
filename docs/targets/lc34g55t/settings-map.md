# Settings map (0x204000..0x2043ff)

Settings RAM, loaded from EEPROM at boot. Mapped so far (offset from 0x204000). Fill this table with the
`map-setting` skill: change one OSD setting, read the `setting-changed` event, record it here and in
`client/src/monitor_events/protocol.py` (`SETTING_NAMES`, `SETTING_ITEMS`).

| Offset | Meaning | Menu item | How confirmed |
|---|---|---|---|
| `0x089` | model string (14 bytes) | | dump |
| `0x09a..0x0b9` | serial number (two copies); masked by clients | | dump |
| `0x0c6` | increments by one per boot (counter) | | events across reboots |
| `0x0cd`, `0x0d4` | changed together during a user OSD session (unknown) | | event |
| `0x0d7` | power/flags: bit0 power on, bit6 DDC/CI enabled | | code + events |
| `0x0de` | source select (1 DP, 2 HDMI) | | code + events |
| `0x0e4` | current window | | code |
| `0x0e5` | window 0 input port (0 DP, 1 HDMI) | | code + events |
| `0x1c2` | energy-cap backlight level (52) | | code |
| `0x1d3` | brightness | `0x0d` | hardware |
| `0x1d6` | energy mode (VCP F7; 0 = cap off) | `0x31` | code |
| `0x1d7`, `0x1d8`, `0x1d9` | red, green, blue gain | `0x11`, `0x12`, `0x13` | code + events |
| `0x1da` | contrast | `0x0e` | hardware |
| `0x1df` | sharpness | `0x0f` | code |
| `0x1e0` | Samsung VCP F3 value | `0x04` | code |
| from `0x1c0` | blocks of ~0x3d bytes repeated per picture mode | | dump pattern |

The menu engine has 111 items (`0x00..0x6e`); 64 use the generic apply path. OSD text tables are per language
(pointer tables around `0x3f98d8`, `0x3faf30`).
