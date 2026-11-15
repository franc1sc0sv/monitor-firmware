# ADR-0006: RAM block reserved by moving the sbrk base and the BSS bound

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

There is no free RAM: BSS runs 0x4c1ea0..0x4fe6b0 and the heap (sbrk, limit 0x800000) starts right after, with its base word at 0x4c1390. The entry code clears BSS up to an immediate in `ori r4,r4,0xe6b0` at 0x2001a7.

## Decision

Move both up by 0x800: sbrk base 0x4feeb0 and BSS bound 0xeeb0. The 2 KB at 0x4fe6b0 belong to the patch and are zeroed on every boot.

## Consequences

The heap loses 2 KB of ~3 MB. Anything that assumed a fixed heap start would break; nothing observed did.
