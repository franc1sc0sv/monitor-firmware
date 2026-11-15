# ADR-0009: Get VCP 0x60 reports the input on screen

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

Stock firmware answers Get 0x60 with the number of the port the query arrived on: during a switch, HDMI said 6 and DP said 9 at the same moment. That is why host software could never confirm a switch.

## Decision

Replace the 0x60 case to read the main-window port `cfg[0xe5 + cfg[0xe4]]` and map 0 -> 0x09 (DP), 1 -> 0x06 (HDMI), else 0x0a.

## Consequences

Every connected host sees the same truth. Values stay the stock Samsung encoding, not the MCCS values the capabilities string advertises.
