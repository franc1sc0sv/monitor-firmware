# Add another monitor

1. Identify the scaler (capabilities string, EDID, board photos) and whether the vendor firmware is signed or
   encrypted. If it is, stop and re-read docs/legal.md before publishing anything.
2. Find a raw-I2C path to the ISP address (direct HDMI to an AMD GPU worked for the LC34G55T; USB-C/HDMI adapters
   only pass EDID).
3. Dump twice, compare hashes, map the container (`docs/hardware/`), then create `firmware/targets/<model>/` with
   `target.toml`, `versions/`, `patches/`, `listings/`.
4. Before two patched monitors share a host, implement ADR-0018 (identity read and `--monitor`).
