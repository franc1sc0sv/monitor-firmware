---
paths:
  - "firmware/**"
  - "tools/ghidra/**"
---
# Patch rules

- Real RAM addresses only (AP body at 0x203800). Every overwritten site must be covered by a guard (stock SHA-256 or
  zero cave) in the version TOML; `mfw check-listing` and `uv run pytest tests/test_golden_listings.py` must pass.
- Use only r3..r8; save r9 around nested `jal`; keep r11..r13 intact in Get handlers (stock reply tail uses them).
- Prefer redirecting a call/tail jump/table entry over rewriting stock code (ADR-0010).
- Stay inside the cave (`0x399820..0x39a000`, 71 % used by v3.1). Data never goes in the cave.
- The assembler's "encoding notes" must stay empty apart from label branches; every form must appear in the stock
  compiler output (`MnemLens.java`).
- Regenerate and commit the golden listing with any source change.
