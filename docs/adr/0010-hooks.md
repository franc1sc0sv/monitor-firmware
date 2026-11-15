# ADR-0010: Hook by redirecting calls and table entries; do not rewrite stock functions

- **Status:** Accepted
- **Date:** 2026-11-15
- **Evidence:** confirmed on hardware

## Context

Rewriting stock functions risks subtle breakage that is hard to see without a debugger.

## Decision

Hooks replace a single call or tail jump (main loop DDC call, Set VCP dispatch, timer ISR tail) or a jump-table entry, call the stock routine, and add behaviour around it. Only the Get 0x60 case block is replaced. Hook code uses only caller-saved registers (r3..r8), saves r9 around nested calls, and leaves r11..r13 for the stock Get tail.

## Consequences

Behaviour of the stock firmware is preserved by construction. Every overwritten site has a guard in the version map.
