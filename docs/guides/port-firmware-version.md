# Port the patch to another firmware version

Porting is not an address swap: 1012.1 uses different RAM offsets (e.g. reply bytes at `0x4c4e36` instead of `0x4c1b1e`).

1. Dump and `mfw identify` (it will say "unknown firmware" and print the AP SHA-256).
2. Unpack, import into Ghidra at 0x203800 (`run-headless.sh import-ap`).
3. Find each symbol of `versions/1006.0.toml` by byte pattern (functions keep their bodies across versions; see the
   journal: Get VCP handler, Set dispatch, main loop, timer ISR tail, Get table, cfg pointer, sbrk word, BSS bound).
4. Write `versions/<new>.toml` with identity, container, cave (prove it unused with `RefsInRanges.java`), RAM block
   and symbols; re-target the patch addresses; assemble; add guards with stock hashes from the new dump.
5. Run the HIL checklist before calling it supported.
