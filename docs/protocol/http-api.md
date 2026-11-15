# Local HTTP API (`monitor-events serve`)

Listens on `127.0.0.1:8765` only. Requests must carry `Host: 127.0.0.1:<port>` or `localhost:<port>`; a foreign
`Origin` is rejected; POST bodies must be `Content-Type: application/json`. This keeps web pages from driving the
monitor (ADR-0013). Start with `uv run monitor-events serve` (`--simulate` for a fake monitor).

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/` | | Web UI |
| GET | `/api/status` | | input, signal, power, clock, event count, picture controls |
| GET | `/api/events` | `?since=SEQ` | events after SEQ (default: last 64) |
| GET | `/api/stream` | | Server-Sent Events, `event: monitor`, one JSON event per message |
| POST | `/api/input` | `{"target":"dp"\|"hdmi"}` | waits for the firmware verdict: `{"ok","verdict","text","elapsed_s","event"}` |
| GET | `/api/vcp/<hex>` | | `{"supported","current","max","name"}` |
| POST | `/api/vcp/<hex>` | `{"value": n}` | written and read back when readable: `{"confirmed","attempts",...}` |
| GET | `/api/settings` | `?raw=1` to unmask | 1 KB settings block as hex (serial masked by default) plus known names |
| GET | `/api/peek` | `?addr=hex&len=n[&raw=1]` | RAM `0x200000..0x7fffff` |
| POST | `/api/poke` | `{"addr":"2041d3","value":80,"apply":13}` | writes a settings byte; applies the known menu item automatically |
| POST | `/api/apply` | `{"item": n}` | applies menu item `0..0x6e` |
| GET | `/api/inventory` | | every known VCP code with current/max |
| GET | `/api/meta` | | event and VCP name tables |

Example: `curl -X POST -H 'Content-Type: application/json' localhost:8765/api/input -d '{"target":"dp"}'`.
