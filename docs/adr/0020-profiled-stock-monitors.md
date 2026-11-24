# ADR-0020: Control known stock monitors through data profiles

- **Status:** Accepted
- **Date:** 2026-11-23
- **Evidence:** confirmed on hardware (Odyssey G5 32" stock firmware, Windows PC over DisplayPort)

## Context

`monitor-ddc` controlled only monitors whose read-only probe (Get 0xEA) confirms the patched firmware protocol, and
never wrote to anything else. The 32" Odyssey G5 runs stock Novatek firmware and has no patch yet (and a patch is
the slowest, riskiest part of the Tandem plan), so Tandem could not switch it at all. Measured on 2026-11-23: the G5
lists `model(LEMON23)` and `60(11 0F)` in its capabilities, Set 0x60 = 0x0F shows DP and 0x11 shows HDMI, Get 0x60
reports the input on screen (it read 0x11 over DP while the Mac on HDMI was shown), and it ignores 0xD6.

## Decision

A stock monitor may be written to only when a built-in **profile** (data in `crates/monitor-ddc/src/profile.rs`)
matches it, checked with reads only, after the 0xEA probe said "not compatible":

1. EDID manufacturer and product id are in the profile;
2. the capabilities string contains the profile's model token;
3. the capabilities list both of the profile's input values under VCP 0x60.

A profiled monitor gets only standard MCCS Sets the profile names (today: 0x60 with the profile's values). Vendor
codes (0xE0..0xFF) are sent only after the 0xEA probe passes, never on the profile path. Input changes are found by
polling Get 0x60; a switch is `Accepted` when Get 0x60 reports the target (the stock firmware has no "picture
locked" signal, so this is weaker than the patched `switch-done`).

## Consequences

- Tandem can switch both monitors today; the G5 reports `profiled` and `Accepted` instead of `Confirmed`.
- A new or repaired stock monitor of a known model needs only a profile entry. An unknown monitor is still never
  written to.
- The G5 accepts a switch at once (Get 0x60 changes immediately) and the picture follows 1-2 s later.
- Power is not controllable on the G5 (0xD6 ignored) and not wakeable over DP on the 34" (`PowerControl` records it).
