# Architecture decision records

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions with evidence levels | Accepted |
| [0002](0002-monorepo.md) | One monorepo: firmware, tools, client, docs | Accepted |
| [0003](0003-repack-raw-deflate.md) | Repack the AP as raw DEFLATE; keep every checksum consistent | Accepted |
| [0004](0004-aeon-load-base.md) | AEON memory model: AP body at 0x203800, little-endian data | Accepted |
| [0005](0005-code-cave.md) | New code lives in the end-of-.text padding | Accepted |
| [0006](0006-ram-block.md) | RAM block reserved by moving the sbrk base and the BSS bound | Accepted |
| [0007](0007-event-ring.md) | Event log: 64-record ring, 10 ms clock, polled from the main loop | Accepted |
| [0008](0008-vcp-range.md) | Expose everything through standard Get/Set VCP in the manufacturer range | Accepted |
| [0009](0009-get60-real-input.md) | Get VCP 0x60 reports the input on screen | Accepted |
| [0010](0010-hooks.md) | Hook by redirecting calls and table entries; do not rewrite stock functions | Accepted |
| [0011](0011-assembler.md) | Assembler is a Ghidra SLEIGH script with an encoding whitelist | Accepted |
| [0012](0012-isp-over-adl.md) | Flash access: MStar ISP over AMD ADL on HDMI | Accepted |
| [0013](0013-http-api.md) | Client: localhost HTTP JSON + SSE, single-file UI, zero dependencies | Accepted |
| [0014](0014-flash-per-sector.md) | Flash per 4 KB sector with erase, program, verify and safe failure | Accepted |
| [0015](0015-memory-access-model.md) | Memory access: read RAM, write only settings, apply through the stock menu call | Accepted |
| [0016](0016-no-vendor-binaries.md) | Vendor binaries and anything derived from them never enter the repository | Accepted |
| [0017](0017-version-maps.md) | Per-firmware-version address maps with expected-byte guards | Accepted |
| [0018](0018-multi-monitor-identity.md) | Identify monitors by firmware identity, not clock proximity | Proposed |
| [0019](0019-standalone-assembler.md) | Standalone AEON assembler for the patch subset | Proposed |
| [0020](0020-profiled-stock-monitors.md) | Control known stock monitors through data profiles | Accepted |
