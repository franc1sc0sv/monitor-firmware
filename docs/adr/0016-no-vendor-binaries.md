# ADR-0016: Vendor binaries and anything derived from them never enter the repository

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed in bytes

## Context

Firmware is Samsung/MStar copyright; dumps and built images embed the unit's serial number.

## Decision

`data/` and `out/` are ignored; CI and a test fail on binaries, large files and serial patterns. Version maps hold SHA-256 of stock bytes, never the bytes. Users build from their own dump.

## Consequences

End users can reproduce the build without receiving vendor code. Decompiled C is not published.
