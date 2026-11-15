# ADR-0014: Flash per 4 KB sector with erase, program, verify and safe failure

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

A failed write followed by a reset boots a half-written AP.

## Decision

Erase, program (256-byte pages, split I2C writes), read back and compare each sector, three tries; skip unchanged sectors; refuse the boot area below 0x11000; require a backup and check the image equals it outside the range; exit non-zero and do not reset on failure so the backup can be written back immediately.

## Consequences

About 10 minutes for the AP region. The JEDEC id gate (EF 40 17) prevents writing an unexpected chip.
