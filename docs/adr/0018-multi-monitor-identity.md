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
