# monitor-events

Client, local API and web UI for the patched Samsung LC34G55T firmware (v3.1). It talks to the monitor over
standard DDC/CI, so it needs no drivers: on Windows it uses the built-in dxva2 API, on Linux `/dev/i2c-*`, and on
macOS (Apple Silicon) IOAVService. Linux and macOS are written but not yet tested.

Part of the monitor-firmware repo; see the root README and `docs/protocol/`.

## Run

```
uv run monitor-events serve          # API + UI on http://127.0.0.1:8765/ (loopback only)
uv run monitor-events --simulate serve   # against the built-in FakeMonitor, no hardware
uv run monitor-events status | history | watch --exec CMD | switch dp|hdmi
uv run monitor-events vcp get 10 | vcp set 10 80 | inventory
uv run monitor-events peek 4fe6b0 64 | poke 2041d3 80 | apply 0x0d | dump-settings   # serial masked; --raw to show
```

On Windows, double-click `start-monitor-ui.cmd`.

## HTTP API

See `docs/protocol/http-api.md`. Loopback only; Host and Origin are checked and POST bodies must be JSON, so web
pages cannot drive the monitor.

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
