# ADR-0017: Per-firmware-version address maps with expected-byte guards

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed in bytes

## Context

Applying a listing to a different firmware version would build a bricking image without any error.

## Decision

`firmware/targets/<model>/versions/<version>.toml` holds identity (AP SHA-256), container layout, cave, RAM block, symbols and guards. `mfw build` refuses unknown versions and any listing block not covered by a guard whose stock hash matches.

## Consequences

A new version is a new TOML plus re-assembled listings; it is not an automatic address swap (1012.1 has different RAM offsets).
