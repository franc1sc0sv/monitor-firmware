# ADR-0019: Standalone AEON assembler for the patch subset

- **Status:** Proposed
- **Date:** 2026-11-15
- **Evidence:** inferred

## Context

Ghidra plus a vendor-derived RAM image is a heavy dependency for re-assembling.

## Decision

Consider a small Python assembler for the ~32 mnemonics the patches use, validated byte-for-byte against the golden listings.

## Consequences

Decide once a second firmware version or target shows how often patches are re-assembled.
