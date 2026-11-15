---
paths:
  - "client/**"
  - "docs/protocol/**"
---
# Protocol and client rules

- A protocol change updates `docs/protocol/vcp-interface.md`, `docs/protocol/CHANGELOG.md`, the client tables in
  `protocol.py`, `simulate.py` (FakeMonitor) and adds a test. Additive changes keep the version; incompatible ones bump it.
- The client has zero runtime dependencies; Python >= 3.10.
- The HTTP API stays loopback-only with Host/Origin checks and JSON-only POST (ADR-0013).
- Mask the serial number in every output by default (`mask_serial`); `--raw`/`?raw=1` only on explicit request.
- Writes must be confirmed by reading back when the code is readable (`EventLog.set_vcp`).
