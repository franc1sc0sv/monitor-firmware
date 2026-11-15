# ADR-0013: Client: localhost HTTP JSON + SSE, single-file UI, zero dependencies

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

Tandem and other apps in any language need native access. A local server avoids per-language DDC bindings. A browser page must not be able to drive the monitor.

## Decision

`monitor-events serve` exposes JSON endpoints and Server-Sent Events on 127.0.0.1 only, serves a single HTML file, and rejects foreign Host/Origin headers and non-JSON POSTs. One lock serialises all bus traffic.

## Consequences

Any program on the PC can control the monitor; nothing off the machine or in a web page can. The package name `monitor-events` undersells it; rename before a 1.0 if wanted.
