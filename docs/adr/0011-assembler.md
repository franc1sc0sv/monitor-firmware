# ADR-0011: Assembler is a Ghidra SLEIGH script with an encoding whitelist

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed in bytes

## Context

There is no public AEON toolchain. Ghidra's SLEIGH assembler works for the plugin, but proposed encodings the stock compiler never emits (for example a 3-byte movhi), and branch sizes oscillated between passes.

## Decision

`AsmPatch2.java` picks encodings seen verbatim in the stock image, uses the longest form for label branches so layout converges, and fails if it does not. Every form used must appear in the stock compiler output (`MnemLens.java`). The independent `mfw check-listing` verifies contiguity, branch targets and text round-trip. Golden listings are committed.

## Consequences

Assembling needs Ghidra plus a RAM image derived from the user's own dump; building does not. See ADR-0019 for a standalone assembler.
