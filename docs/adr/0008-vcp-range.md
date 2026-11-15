# ADR-0008: Expose everything through standard Get/Set VCP in the manufacturer range

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

Custom DDC opcodes would need raw I2C, which stock OS APIs (dxva2, many drivers) do not offer. Codes 0xEA..0xEF and 0xF0..0xF2 are 'unsupported' in the stock Get table; Samsung uses 0xE0..0xE2, 0xE5, 0xE6, 0xE9, 0xF3, 0xF5, 0xF7, 0xFE.

## Decision

The event log and memory access use VCP 0xEA..0xF6 over plain MCCS Get/Set VCP. See docs/protocol/vcp-interface.md.

## Consequences

Works through Windows dxva2 with any GPU (verified on AMD and NVIDIA), Linux i2c-dev and macOS IOAVService. Each value is 4 bytes per reply, so reads are chatty (about 1 KB per 22 s).
