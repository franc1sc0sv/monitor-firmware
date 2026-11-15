# ADR-0001: Record architecture decisions with evidence levels

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed in bytes

## Context

Most decisions in this project rest on reverse-engineering findings that range from byte-exact facts to educated guesses. Future sessions (human or AI) need to know which is which before building on them.

## Decision

Keep short ADRs in `docs/adr/NNNN-title.md` (Nygard form) with an extra **Evidence** field: *confirmed on hardware* (observed on the real monitor), *confirmed in bytes* (verified against the firmware image or a hash), or *inferred* (reasoned from code, not measured). The dated research trail stays in `docs/targets/<model>/journal.md`; reference pages hold only current truth.

## Consequences

A claim may be called confirmed only with bytes, a hash or a hardware observation. Superseded ADRs are kept and marked.
