# monitor-firmware

Custom firmware patches and tooling that make a Samsung monitor tell the truth about itself over DDC/CI:
which input is really on screen, whether an input switch worked, and a timestamped log of everything that changes
inside it. Plus a cross-OS client with a local HTTP API and a web UI.

> **Warning.** Flashing modified firmware can permanently disable your monitor and voids the warranty. Recovery
> may require opening it and an external SPI programmer. Tested on exactly one unit. Read [docs/safety.md](docs/safety.md).
>
> Not affiliated with or endorsed by Samsung or MStar. No vendor firmware is included: you build from a dump of your
> own monitor.

## Status

| Monitor | Firmware | Patch | State |
|---|---|---|---|
| Samsung LC34G55T (MStar MST9U) | 1006.0 | v3.1, protocol 2 | Flashed and verified on hardware |
| Samsung LC34G55T | 1012.1 | none | Addresses differ; not ported |
| Samsung Odyssey G5 ("FALCON") | stock | none | No MStar ISP on direct HDMI; likely Novatek (see roadmap) |

| Client backend | State |
|---|---|
| Windows (dxva2, any GPU) | Tested |
| Linux (i2c-dev, display buses with EDID only) | Written, untested |
| macOS Apple Silicon (IOAVService) | Written, untested |

## What the patch adds

- `Get VCP 0x60` reports the input actually on screen (stock answered with the port you asked from).
- A 64-entry event ring with a 10 ms clock: boot, input changes (DDC, buttons or auto), signal, sync, power,
  OSD state, every settings byte that changes, and a firmware verdict for each switch request (done or failed).
- Memory read, settings write and menu-item apply, all over standard Get/Set VCP (codes `0xEA..0xF6`), so stock
  OS APIs work. Spec: [docs/protocol/vcp-interface.md](docs/protocol/vcp-interface.md).

## Quick start (client)

```bash
uv sync
uv run monitor-events status                 # live state from the patched monitor
uv run monitor-events switch dp              # switch and wait for the firmware's verdict
uv run monitor-events watch --exec ./on-event.sh
uv run monitor-events serve                  # API + UI on http://127.0.0.1:8765/
uv run monitor-events --simulate serve       # same, against a built-in fake monitor
```

API: [docs/protocol/http-api.md](docs/protocol/http-api.md). On Windows: `client/start-monitor-ui.cmd`.

## Building and flashing

[Dump](docs/guides/dump.md) twice and compare hashes, [build](docs/guides/build.md) with `mfw` (refuses unknown
firmware and any patch site whose stock bytes do not match), [flash](docs/guides/flash.md), and keep the
[recovery](docs/guides/recover.md) steps at hand. Contributors: [assemble](docs/guides/assemble.md).

## Layout

| Path | Contents |
|---|---|
| `firmware/targets/<model>/` | target facts, per-version address maps with guards, patch sources, golden listings |
| `tools/mfw/` | `mfw`: identify, verify, check listings, guarded rebuild (Python) |
| `tools/ghidra/` | Ghidra headless scripts, including the AEON assembler |
| `tools/windows/` | ISP dump/flash and DDC tools over AMD ADL (PowerShell + C#) |
| `client/` | `monitor-events`: protocol client, CLI, HTTP API, web UI, fake monitor |
| `docs/` | protocol, hardware, guides, ADRs, per-monitor pages and research journal |

## Documentation

[docs/index.md](docs/index.md) · [ADRs](docs/adr/README.md) · [roadmap](docs/roadmap.md) ·
[LC34G55T](docs/targets/lc34g55t/overview.md)

## License

Code: [MIT](LICENSE). Documentation: CC BY 4.0. The licenses cover this repository's own content only and grant
nothing over Samsung's or MStar's firmware.
