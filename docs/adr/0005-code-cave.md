# ADR-0005: New code lives in the end-of-.text padding

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed in bytes

## Context

The AP entry configures .text as 0x20c000..0x39a000 and MIU-protects it. 0x399817..0x39a000 (2025 bytes) is zero padding with no references (RefsInRanges, pointer scans).

## Decision

New code goes in the cave from 0x399820 to 0x39a000, guarded as zero in the version map. The region is write-protected at run time, so it holds code only, never data.

## Consequences

v3.1 uses 1439 of 2016 bytes (71 %). The next feature needs a size pass or a second cave; the builder and listing checker enforce the bound.
