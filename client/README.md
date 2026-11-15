# monitor-events

Client, local API and web UI for the patched Samsung LC34G55T firmware (v3.1). It talks to the monitor over
standard DDC/CI, so it needs no drivers: on Windows it uses the built-in dxva2 API, on Linux `/dev/i2c-*`, and on
macOS (Apple Silicon) IOAVService. Linux and macOS are written but not yet tested.

## Run

```
uv run monitor-events serve          # API + UI on http://127.0.0.1:8765/
uv run monitor-events status | history | watch --exec CMD | switch dp|hdmi
uv run monitor-events vcp get 10 | vcp set 10 80 | inventory
uv run monitor-events peek 4fe6b0 64 | poke 2041d3 80 | apply 0x0d | dump-settings
```

On Windows, double-click `start-monitor-ui.cmd`.

## HTTP API (JSON, CORS open, localhost only by default)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/status` | | input, signal, power, clock, event count, picture controls |
| GET | `/api/events` | `?since=SEQ` | events after SEQ (default: last 64) |
| GET | `/api/stream` | | Server-Sent Events, `event: monitor`, one JSON event per message |
| POST | `/api/input` | `{"target":"dp"\|"hdmi"}` | waits for the firmware's verdict: `{"ok", "verdict", "text", "elapsed_s"}` |
| GET | `/api/vcp/<hex>` | | `{"supported", "current", "max"}` |
| POST | `/api/vcp/<hex>` | `{"value": n}` | written and read back |
| GET | `/api/settings` | | 1 KB settings block 0x204000..0x2043ff as hex, plus known names |
| GET | `/api/peek` | `?addr=hex&len=n` | RAM 0x200000..0x7fffff |
| POST | `/api/poke` | `{"addr":"2041d3","value":80,"apply":13}` | writes a settings byte (0x204000..0x2043ff only), applies the menu item (auto when known) |
| POST | `/api/apply` | `{"item": n}` | applies menu item 0..0x6e, as the OSD does |
| GET | `/api/inventory` | | every known VCP code with current/max |

Example from any language: `curl -X POST localhost:8765/api/input -d '{"target":"dp"}'`.

## Event ids

| id | name | old / new |
|---|---|---|
| 0x00 | boot | |
| 0x01 | input-port | port before / after (0 DP, 1 HDMI) |
| 0x02 | source-select | |
| 0x03 | power-flags | bit0 = power on |
| 0x04 | powersave-flags | |
| 0x05 | sync-flags | 0x0a = picture locked |
| 0x06 | signal | 0 lost / 1 present |
| 0x07 | system-state | |
| 0x08 | window-port | |
| 0x10 | ddc-switch-request | current port / requested VCP value |
| 0x11 | switch-done | target port active and picture locked |
| 0x12 | switch-failed | no locked picture on the target within 8 s |
| 0x13 | ddc-power-request | / requested D6 value |
| 0x20, 0x21 | setting-changed | offset low byte (high bit in id) / new value |
