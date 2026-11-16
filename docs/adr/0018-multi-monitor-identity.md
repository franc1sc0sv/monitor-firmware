# ADR-0018: Identify monitors by firmware identity, not clock proximity

- **Status:** Proposed
- **Date:** 2026-11-15
- **Evidence:** inferred

## Context

`find_logs` groups paths to one monitor when their clocks agree within 1 s. Two patched monitors powered together would merge.

## Decision

Add an identity/capability read (proposed Get 0xF5 is Samsung-used; pick a free code) returning a capability bitmap and a per-unit id derived from the serial hash, and a `--monitor` selector in the client.

## Consequences

Required before the Odyssey G5 gets the patch.

## Update 2026-11-16

The Tandem plan (`docs/integration/tandem.md` §3.3) identifies monitors client-side as `<profile>-<hash of EDID
serial>`, which needs no firmware change and works on the stock/bricked-then-repaired G5. The firmware identity read
stays optional. Note the G5 dev hook reuses VCP `0xF0..0xF8` with different meanings, so the client must choose the
driver from profile + Get-only probe before sending any vendor code.
