# ADR-0007: Event log: 64-record ring, 10 ms clock, polled from the main loop

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

The firmware has no event mechanism. The main loop calls the DDC service every iteration; the 1 ms timer ISR ends with a tail call. The stock 10 ms counter (0x4cea40) turned out to be reset by firmware code, giving non-monotonic times.

## Decision

A poller hooked into the main loop compares watched values with a snapshot and logs changes into a 64 x 8-byte ring (u16 sequence, id, old, new, 24-bit time). The clock is our own: the ISR tail hook counts milliseconds into a 32-bit 10 ms counter. A settings scanner compares 8 bytes per pass of 0x204000..0x2041ff with a shadow copy. Switch verdicts require the target port and sync flags 0x0a.

## Consequences

Watches are generic (byte compare), so new state is cheap to add but needs naming. Events can be missed only if more than 64 happen between client reads (detected as a sequence gap).
