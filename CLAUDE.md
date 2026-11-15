# monitor-firmware

Custom firmware patches + tooling for Samsung monitors (MStar MST9U scaler, AEON R2 CPU) so the monitor reports its
real state and events over DDC/CI, plus a cross-OS client (`monitor-events`) with a localhost HTTP API and web UI.
First target: LC34G55T, firmware 1006.0, running patch v3.1 (protocol 2). Read `docs/roadmap.md` first in a new session.

## Hard rules

- Never commit or print anything from `data/` or `out/` (vendor firmware, dumps, built images, Ghidra projects).
  Never put a serial number in any tracked file, issue or message. `uv run pytest tests/test_repo_hygiene.py` checks.
- Never flash without the user's explicit go-ahead **in the current session**, and only through `tools/windows/flash.ps1`
  following the `flash-monitor` skill. Never write below `0x11000`. Always have a verified backup.
- Every overwritten firmware site needs a guard in `firmware/targets/<model>/versions/<version>.toml`; addresses go in
  data files, not in client/tool code.
- A finding is "confirmed" only with bytes, a hash, or a hardware observation; otherwise say "inferred" (ADR-0001).
- After a firmware or protocol change: regenerate the golden listing, update `docs/protocol/`, add a FakeMonitor test.
- Project docs, code comments and commit messages are in English. Commits carry only the user's identity.

## Facts that bite

- AEON data is **little-endian** although Ghidra models the core as BE. AP body loads at **0x203800**, prefix at 0x200000.
- Hook code uses only r3..r8, saves r9 around `jal`, never touches r11..r13 in Get handlers.
- `b.movi` is 4-bit; use `b.ori rX,r0,imm`. Conditional branches are short: branch locally, then `b.j`.
- The code cave (`0x399820..0x39a000`) is MIU write-protected: code only. RAM state lives in the 2 KB block at 0x4fe6b0.
- `.ps1/.psm1/.cmd` are CRLF (`.gitattributes`). PowerShell runs from WSL via
  `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe` after `cd /mnt/c`, with paths from `wslpath -w`.
- Windows `localhost` is reachable from WSL (`curl http://127.0.0.1:8765/api/status` when the server runs on Windows).
- ISP/flash tools need the monitor's HDMI on the AMD iGPU and that connection active. DDC/CI also works over NVIDIA DP.

## Commands

```bash
uv sync                                   # workspace: client + tools/mfw + dev tools
uv run pytest                             # 39+ tests, no hardware needed
uv run ruff check && uv run ruff format --check && uv run pyright
uv run mfw identify|verify|check-listing|build ...      # docs/guides/build.md
uv run monitor-events [--simulate] status|history|watch|switch|serve|vcp|peek|poke|apply|dump-settings
tools/ghidra/run-headless.sh assemble <patch.s> <out.lst>                  # docs/guides/assemble.md
```

## Where things are

- Protocol spec: `docs/protocol/vcp-interface.md`; HTTP API: `docs/protocol/http-api.md`
- Decisions: `docs/adr/`; per-monitor truth: `docs/targets/lc34g55t/overview.md`, `settings-map.md`
- History/evidence: `docs/targets/lc34g55t/journal.md` (old sections use base 0x200000: add 0x3800)
- Skills: `.claude/skills/` (assemble-patch, build-image, flash-monitor, restore-stock, map-setting,
  port-firmware-version, re-query, hil-check). Path rules: `.claude/rules/`.
