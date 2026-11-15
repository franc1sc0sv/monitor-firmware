# Build a patched image

End users do not need Ghidra: the golden listing is the assembled patch.

```bash
uv sync
uv run mfw identify data/dumps/LC34G55T-full-1.bin           # must name a known version
uv run mfw check-listing firmware/targets/lc34g55t/listings/1006.0/v3-full.lst
uv run mfw build data/dumps/LC34G55T-full-1.bin \
    --listing firmware/targets/lc34g55t/listings/1006.0/v3-full.lst \
    --out out/lc34-v3.1.bin --engine zopfli
uv run mfw verify out/lc34-v3.1.bin
```

`build` refuses unknown firmware, a dump that does not round-trip byte-identically, any listing block not covered by
a guard whose stock hash matches, and any change outside the allowed flash range. It prints the flash range for
`flash.ps1`. With the 1006.0 dump, the result is byte-identical to the image flashed and verified as v3.1
(sha256 `620699f3…`).
