# Roadmap and open work

State on 2026-11-15: LC34G55T runs v3.1 (protocol 2). Client 0.3.0 with HTTP API and UI. Both monitors were left on
DisplayPort at the end of the session.

## Next

- **Inactive HDMI DDC/CI** (`docs/targets/lc34g55t/inactive-hdmi-ddc.md`): run the read-only peek experiment (PC on
  DP peeks the DDC2Bi-only RAM bytes before/after the Mac sends on HDMI). Its result picks a patch (main-loop service,
  ISR check, TX fix) or rules a firmware fix out. No patch is built until then.
1. **Settings map**: map the remaining OSD items (refresh rate, game mode, response time, adaptive sync, eye saver,
   black equalizer, off timer, power LED...). Static route: follow the menu engine (`0x284884`, apply table
   `0x378810`, OSD text tables). Dynamic route: `map-setting` skill with the UI's settings grid.
2. **Scanner covers the whole KB**: today 0x204000..0x2041ff; per-mode blocks extend to 0x2043ff (needs a 1 KB
   shadow, i.e. a 3 KB block, and a cave size pass).
3. **Name events**: system-state values, "manual vs DDC" input change classification in the client.
4. **Energy cap**: event when the backlight source switches to the cap; client command to toggle VCP F7.
5. **Identity/capability read** and `--monitor` selector (ADR-0018) before patching a second monitor.
6. **Odyssey G5 ("FALCON")**: needs a direct HDMI cable to the AMD GPU for ISP; dump, check for signing, new target.
7. **Test the Linux and macOS backends** (macOS: the Mac in the user's setup).
8. Re-test the refactored PowerShell tools on hardware (they need the AMD HDMI connection active).
9. Data-driven patch addresses (`%hi/%lo` symbols rendered from the version TOML), split the patch by feature.
10. Investigate the dual image bank (A/B flashing) and document the board for SOIC-8 recovery.

## Known unknowns

- Why the inactive HDMI does not answer DDC/CI (no software gate in the AP; engine, interrupt or PHY level), and
  whether macOS keeps the HDMI display's IOAVService while the monitor shows DP.
- The u16 check word after the AP stream (copied unchanged; boot ignores it; vendor tools might not).
- Behaviour of Samsung's own updater on a patched unit.
- Exact meaning of several watched values (`0x4ca78c`, `0x4cebe4`, `0x4ec92d`).
