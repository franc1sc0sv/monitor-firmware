---
name: assemble-patch
description: Assemble an AEON patch source into a golden listing and verify it. Use when firmware/targets/*/patches/*.s changes or a new listing is needed.
---
# assemble-patch

1. Make sure `data/vendor/ram-installed.bin` (prefix + AP body from the user's own dump) and the Ghidra project
   `data/ghidra-ram/ram` exist; otherwise follow docs/guides/assemble.md step 1.
2. `tools/ghidra/run-headless.sh assemble firmware/targets/<model>/patches/<file>.s out/new.lst`
   (on failure read `out/assemble.log`; common causes: immediate too large for `b.movi`/`b.beqi`, branch out of range).
3. `uv run mfw check-listing out/new.lst --dump data/dumps/<dump>.bin` must print LISTING OK.
4. Read the "---- encoding notes" section: only "label-branch longest form" lines are acceptable.
5. Report the cave end address vs 0x39a000 and the bytes left.
6. If new sites are overwritten, add guards to the version TOML (SHA-256 of stock bytes from the dump).
7. Copy to `firmware/targets/<model>/listings/<version>/` and run `uv run pytest tests/test_golden_listings.py`.
