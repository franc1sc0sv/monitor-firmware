# ADR-0002: One monorepo: firmware, tools, client, docs

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed in bytes

## Context

The firmware patch, the DDC/CI protocol and the client changed together in every release (v1 to v3.1). Comparable projects (joshado/s718ql-firmware-patch) keep firmware, tools and docs together.

## Decision

One repository with `firmware/targets/<model>/` (version maps, patches, golden listings), `tools/` (`mfw` builder, Ghidra scripts, Windows ISP/DDC tools), `client/` (`monitor-events`) and `docs/`. A uv workspace ties the Python packages together.

## Consequences

Protocol changes land with their firmware and client changes in one commit. The client stays installable on its own (zero runtime dependencies). A new monitor is a new `firmware/targets/<model>/` folder.
