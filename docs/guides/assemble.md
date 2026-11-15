# Assemble a patch (contributors)

1. Build a RAM image from your own dump: prefix (`0x3800` bytes at `ap_flash_start`) followed by the inflated body.
   ```bash
   uv run python -c "from mfw import container as c; import pathlib as p; d=p.Path('data/dumps/LC34G55T-full-1.bin').read_bytes(); pre,body=c.unpack(d,c.Layout()); p.Path('data/vendor/ram-installed.bin').write_bytes(pre+body)"
   tools/ghidra/run-headless.sh import-ram data/vendor/ram-installed.bin
   ```
2. Edit `firmware/targets/lc34g55t/patches/lc34-full.s` (syntax: `@0xADDR`, `label:`, `@label` references,
   `.le32`, `.bytes`). Use only `r3..r8`; save `r9` around `jal`; keep the cave bound.
3. Assemble and check:
   ```bash
   tools/ghidra/run-headless.sh assemble firmware/targets/lc34g55t/patches/lc34-full.s out/new.lst
   uv run mfw check-listing out/new.lst --dump data/dumps/LC34G55T-full-1.bin
   ```
   Review the "encoding notes" section (must be empty apart from label branches) and the cave end.
4. If a new site is overwritten, add a guard to the version TOML (SHA-256 of the stock bytes, computed from your dump).
5. Copy the listing to `firmware/targets/lc34g55t/listings/<version>/` and commit it with the source change.
