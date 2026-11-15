# ADR-0004: AEON memory model: AP body at 0x203800, little-endian data

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed in bytes

## Context

The first analysis loaded the AP at 0x200000; jump tables and string pointers did not resolve. With the body at 0x203800 (after the 0x3800 prefix at 0x200000), 517 string pointers resolve versus 29, and the Get VCP jump table lands exactly on its case blocks. The Ghidra plugin models AEON as big-endian, but data words are read little-endian.

## Decision

All addresses in this project are real RAM addresses with the AP body at 0x203800 and the prefix at 0x200000. Data pointers and tables are decoded little-endian. Instruction streams are byte sequences and assemble correctly with the plugin.

## Consequences

Early journal entries use the old base (subtract 0x3800 from them). Decompiler output for loads of 16/32-bit values shows byte-swapped constants; trust the bytes, not the C.
