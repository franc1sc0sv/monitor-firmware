# Contributing

- **Never** attach or commit vendor firmware, flash dumps, built images, Ghidra projects or decompiler output, in
  PRs or issues. Redact serial numbers (the client masks them by default; do not use `--raw` output in issues).
- Mark claims with an evidence level: confirmed on hardware, confirmed in bytes, inferred (ADR-0001).
- Firmware changes: patch source + regenerated golden listing + guards in the version TOML, `mfw check-listing`
  clean, and the HIL checklist (`docs/guides/hil-checklist.md`) results in the PR.
- Protocol changes: update `docs/protocol/vcp-interface.md`, its CHANGELOG, the client, and add a `FakeMonitor` test.
- New firmware version: `docs/guides/port-firmware-version.md`. New monitor: `docs/guides/add-monitor.md`.
- Checks: `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pytest`.
- Do not copy code from GPL projects (flashrom, ddcutil); protocol facts are fine.
- PRs that wrap the stock factory opcodes (`0xC2`, `0xC4` EDID/serial write) will not be accepted.
