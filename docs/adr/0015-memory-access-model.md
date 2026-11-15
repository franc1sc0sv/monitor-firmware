# ADR-0015: Memory access: read RAM, write only settings, apply through the stock menu call

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

Full control needs reading internal state and changing settings that have no VCP code.

## Decision

Get 0xF2 reads 0x200000..0x7fffff; Set 0xF4 writes only 0x204000..0x2043ff; Set 0xF6 applies menu item 0..0x6e through the stock `0x284884(item, 1)`. Nothing can write code, hardware registers or the factory opcodes.

## Consequences

Any host on any cable can read RAM (including the serial) and change settings. Documented in SECURITY.md; clients mask the serial. Open question: gate behind an unlock sequence in a future protocol version.
