# Roadmap and open work

State on 2026-11-15: LC34G55T runs v3.1 (protocol 2). Client 0.3.0 with HTTP API and UI. Both monitors were left on
DisplayPort at the end of the session.

## Next

1. **Settings map**: map the remaining OSD items (refresh rate, game mode, response time, adaptive sync, eye saver,
   black equalizer, off timer, power LED...). Static route: follow the menu engine (`0x284884`, apply table
   `0x378810`, OSD text tables). Dynamic route: `map-setting` skill with the UI's settings grid.
2. **Scanner covers the whole KB**: today 0x204000..0x2041ff; per-mode blocks extend to 0x2043ff (needs a 1 KB
   shadow, i.e. a 3 KB block, and a cave size pass).
3. **Name events**: system-state values, "manual vs DDC" input change classification in the client.
4. **Energy cap**: event when the backlight source switches to the cap; client command to toggle VCP F7.
5. **Identity/capability read** and `--monitor` selector (ADR-0018) before patching a second monitor.
6. **Odyssey G5 ("FALCON")**: tested 2026-11-15 on a direct HDMI link to the AMD iGPU: DDC/CI works, but nothing
   answers at 0x49 (MStar ISP) or 0x59 (SERDB); the bus only ACKs 0x30, 0x37, 0x3A, 0x50, 0x54 (confirmed). The unit
   reports 2560x1440 @ 165 Hz, 70x40 cm, EDID product `7489` (DP) / `748A` (HDMI). Public research on the LS32CG552
   (G55C) says it is a Novatek NT68500 (8051 + SPARC V8 main app) updated by USB `.img` with a byte-sum check
   (inferred for this unit). So the MStar patch does not port: it is a new platform. Next: confirm model and
   firmware version from the label/OSD, obtain the matching stock `.img`, and find a read-back path before any write.
   Set VCP 0x60 accepts `0x06` (to HDMI) but ignored `0x09`, `0x0F`, `0x11`, `0x12`.
7. **Test the Linux and macOS backends** (macOS: the Mac in the user's setup).
8. Re-test the refactored PowerShell tools on hardware (they need the AMD HDMI connection active).
9. Data-driven patch addresses (`%hi/%lo` symbols rendered from the version TOML), split the patch by feature.
10. Investigate the dual image bank (A/B flashing) and document the board for SOIC-8 recovery.

## Known unknowns

- The u16 check word after the AP stream (copied unchanged; boot ignores it; vendor tools might not).
- Behaviour of Samsung's own updater on a patched unit.
- Exact meaning of several watched values (`0x4ca78c`, `0x4cebe4`, `0x4ec92d`).
