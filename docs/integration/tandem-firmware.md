# Firmware for Tandem: both monitors, one protocol

State on 2026-11-23 (Phase A measured, Phase B crate part done). Plan for the firmware work that makes **both** monitors (34" LC34G55T, MStar; 32" G5 FALCON,
Novatek) give Tandem everything it needs: the real input, input switching with a verdict, power on/off by command,
and events. Companion to `tandem.md` (client/API contract). Confidence per ADR-0001: **confirmed** = bytes, hash or
hardware observation; **inferred** otherwise.

## 0. Where we start

| | 34" LC34G55T | 32" G5 FALCON |
|---|---|---|
| Firmware | 1006.0 + patch v3.1, protocol 2 (confirmed) | recovered by SPI programmer 2026-11-22 (sector `0x41F000` rewritten and verified by flashrom, boot tag set to bank A: `data/dumps/g5-offboard/*.log`, confirmed). **Which image runs in bank A (stock 1008.3 or a 1019-1021 dev image) is not recorded** |
| Real input (Get 0x60) | yes (v1 patch, ADR-0009) | **yes, stock** (confirmed 2026-11-23: `0x11` over DP while showing HDMI) |
| Input values | Set `0x09` DP / `0x06` HDMI | Set `0x0F` DP / `0x11` HDMI (confirmed 2026-11-23) |
| Switch verdict | events 0x11/0x12 | none; Get 0x60 reports the target ~0.6 s after the Set, picture 1-2 s later |
| Event ring | 0xEA..0xEF | none in stock; the dev hook reuses 0xF0..0xF8 with **dangerous** meanings (memory write, function call) |
| Power by command | D6 = 4 → standby, **DP link drops**, no way to send D6 = 1 from the PC (confirmed 2026-11-23). Get D6 is stale | **D6 ignored** (1, 4, 5: no effect, confirmed 2026-11-23) |
| Flash route | MStar ISP over the AMD HDMI (proven, `flash-monitor` skill) | USB `.img` updater (proven: 1008.3 and restamped 1009.0, 2026-11-15) + SPI clip as recovery (proven 2026-11-22). The DDC flasher caused the 2026-11-16 brick: **not used for this plan** |
| Client side | `monitor-ddc` opens it as `standard` (protocol 2) | `monitor-ddc` opens it as `profiled g5-falcon` (ADR-0020), switch verified on hardware |

`develop` (the crate) is merged into `g5-falcon`.

## 0.1 Phase A results (2026-11-23, PC over DP, user watching)

| Question | 34" | 32" G5 |
|---|---|---|
| Get 0x60 truthful? | yes (patch) | **yes** (stock) |
| Set 0x60 back to DP | `0x09` | **`0x0F`** |
| Power off by D6 | **yes** (4 → standby, LED on) | **no** (ignored) |
| Power on by D6 from the DP host | **impossible**: the DP link drops with standby, Windows loses the monitor | n/a |
| Wake that worked | power button (came back on HDMI) | n/a |
| Still to measure | DDC from the Mac over HDMI while the 34" is in standby; wake by video signal; OSD input change on the G5 seen by polling | same, plus what image bank A runs |

Side effect seen (confirmed): when the 34" woke on HDMI, the Mac (lid closed, mirroring) saw a new display and
re-arranged both screens; both went black for a few seconds. Tandem must expect display re-arrangement on the Mac
after any switch that makes a monitor appear or disappear for it (R15).

## 0.2 Desk API on the real desk (2026-11-23, Windows PC over DP, user doing the physical steps)

`monitor-ddc` now has one API for both monitors: `Monitor` (status, switch, power, capabilities) and `Desk`
(tracks every monitor by `MonitorId` across scans: `Appeared`, `Off`, `InputChanged { by_this_host }`,
`PowerChanged`, `SignalChanged`; `shows_this_host()` from the EDID product id of the host's port). Checked with
`examples/desk.rs` (Windows build). All results **confirmed** on hardware:

| Test | 34" (standard) | 32" G5 (profiled) |
|---|---|---|
| Status: input, owner (`shows_this_host`) | DP / true; while on HDMI: hdmi / false | HDMI / false; while on DP: dp / true |
| Switch by command | `Confirmed` 3.4-10.4 s; event `by_this_host: true` | `Accepted` 0.44 s; event `by_this_host: true` |
| Change with the OSD buttons | `InputChanged by_this_host: false`, both ways | same, both ways |
| Listed by Windows while showing the other input | **yes** (Present) | yes |
| Power button off / on | `Off` / `Appeared` | `Off` (after the 5 s debounce) / `Appeared`, still `g5-falcon` |
| Power off by command | `Ok`, `Off` 5.5 s later; `power_on` = `Unsupported` | `Unsupported` (nothing sent) |
| Wake by command | impossible (DP drops) | impossible (0xD6 ignored) |
| PC turns its displays off (DPMS) | **firmware hung**: no LED, no DDC, button dead, still listed by Windows; recovered only by unplugging power (R16) | not affected (it showed the Mac) |

Bugs found and fixed during the run: (1) the off debounce of 2 scans turned the 34"'s DP re-train right after boot
(~3 s gone) into a false `Off`: now 5 s and 2 scans; (2) a G5 coming back from off was re-checked by reading its
capabilities, which blocks ~60 s per attempt while it boots (one scan took 266 s) and then failed, leaving it "not
compatible": known units are now reattached without re-reading, capabilities are read once without retries, and
"not compatible" is retried after 30 s.

Not tested yet: a switch to an input with no signal (needs a cable unplugged), the whole API from the Mac over HDMI
(`ssh mac-runner` timed out), the DPMS hang reproduced or compared with stock firmware.



## 0.3 Static RE for the missing pieces (2026-11-23)

Deep static analysis of both firmwares: `docs/targets/lc34g55t/tandem-re.md` and `docs/targets/g5-falcon/tandem-re.md`.

- **34":** standby and power-off hand the board to a second CPU (8051 "PM51" at flash `0x11080..`); the AP spins and a
  wake is a full reboot. PM51 keeps keys and DDC wake, so **D6 = 1 from the Mac over HDMI may already wake stock**
  (inferred). Wake from the DP host needs a **soft standby** patch (D6 = 4 blanks panel/backlight with stock routines,
  AP + DP + DDC stay up; D6 = 1 turns the panel back on). Stock Get 0xD6 points at a reply tail (bug confirmed). The
  DPMS hang (R16) is most likely stock PM behaviour triggered by constant DDC polling in standby, not patch code
  (inferred): `Desk` now probes a listed-but-off monitor at most every 10 s.
- **G5 (corrected after the implementation pass):** stock Set 0xD6 is accepted but does nothing (1/2 no-ops, 4 sets a
  flag nobody reads, 5 unsupported). The power call is `SecLibPower_SetPowerState(1)` (the off timer's call), so
  **power off by D6 is a small patch**; wake needs the same soft-standby idea. Real input already works on stock. The
  "free BSS" area is the C heap's range (`sbrk` from `0xA803C0A8`, no limit): no statically proven free RAM, so the
  p3b/p3c hooks check the heap break on every entry and fall back to stock if it grew over their block.

## 0.4 Built, not flashed (2026-11-23)

| Monitor | Image (local `out/`, gitignored) | What it adds | Runbook |
|---|---|---|---|
| 34" | `lc34-v3.2.bin` (sha256 `bb41db8a…0701`), flash `0x11000..0x2c0000` | protocol 3: 0xE8, Get D6, soft standby (D6 4/1/5, any key wakes), switch guard, events 0x14/0x15. Cave 2005/2016 bytes | `docs/targets/lc34g55t/tandem-re.md` §7 |
| G5 | `g5/M-C5500GGZA-1030.0[BFFA].img` p3a | 0xE8, Get D6, D6 = 4/5 power off | `docs/targets/g5-falcon/tandem-re.md` §5 |
| G5 | `g5/M-C5500GGZA-1031.0[C0D3].img` p3b | + soft standby (D6 4/1); the power key in soft standby powers off | same |
| G5 | `g5/M-C5500GGZA-1032.0[B260].img` p3c | + event ring 0xEA..0xEF, verdicts, switch guard, 0x14/0x15 | same; free-RAM soak first |

Session order: `docs/integration/tandem-hil.md`. Known gaps of the G5 p3c image: events are sampled when the host
polls (no main-loop tap); event times and the 0xEF clock tick in 1 s steps and wrap daily, so `monitor-ddc` would see
one false "rebooted" a day (re-reads the ring, no loss) until the crate or the image handles it; source detection
not located (bit 5 = 0); soft standby keeps audio.

## 0.5 34" v3.2 flashed (2026-11-23, user present and approving)

- Backup: two ISP reads of the installed flash, equal (`7fd8c35d…`), identical to v3.1 + stock trailer; kept locally
  as `data/dumps/lc34-v3.1-installed.bin`.
- Flashed `out/lc34-v3.2-flash.bin` (v3.2 with the installed trailer sector, sha256 `e53938d1…`) over
  `0x11000..0x161000` with `flash.ps1` (refactored tool, first hardware use: test mode OK, write OK, 297 sectors in
  573 s). The 0x2bf000 trailer CRC stays stale exactly as with v3.1 (boot does not check it). Reads take ~830 s each.
- After boot (**confirmed**): Get 0xEA ML = 3, 0xE8 = caps `0x01FF`, cable mask `0x03`, flags bit 1 = source
  detection manual (Auto Source Switch off); Get D6 = 1; picture, joystick and OSD normal (key wrapper transparent).
- Soft standby (**confirmed**): D6 = 4 → Get D6 = 4, flags bit 0, events `0x13`, `0x14 1→4`; the monitor stays
  listed by Windows; D6 = 1 wakes it (`0x14 1→1`). Through `monitor-ddc` `Desk`: `power_off` → `PowerChanged
  Standby` in 0.7 s, `power_on` → `PowerChanged On`, `shows_this_host` true again. **The first attempt had no
  visible effect** (state and events changed, panel stayed on) right after the user had used the OSD; the second
  blanked and woke correctly. Inferred: panel-off is ignored while the OSD is active. To check: repeat with and
  without OSD use; if confirmed, the patch must wait for the OSD to close or close it first.
- Power button off/on on v3.2 (**confirmed**): `Desk` `Off` then `Appeared`, as on v3.1.
- Switch guard and cable detect (**confirmed**): HDMI cable unplugged → 0xE8 MH = `0x01`, event `0x15 03→01`;
  `Desk::switch(hdmi)` → `Failed { current: DisplayPort }` in 0.65 s, no input change (events `0x10`, `0x12`);
  cable plugged into the Mac (awake) → `0x15 01→03`. Cable polarity is right (bit set = present).
- Not yet tested on v3.2: key wake from soft standby, D6 = 5, the display-sleep test with Auto Source Switch off,
  a sleeping Mac's cable state.

## 0.6 G5 back to stock content (2026-11-23)

- The OSD showed **1021.4** (the dev image with the memory write/call hook). The USB updater **refuses a lower
  version** ("older than the current one"), so stock 1008.3 cannot be installed directly over a higher number.
- Built `out/g5/M-C5500GGZA-1029.0[C145].img` = stock 1008.3 with only the version digits changed (3 bytes, sum16 tag
  unchanged), copied with native Windows to the FAT32 stick, hash checked. The G5 accepted it; OSD shows **1029.0**.
  From the PC: `profiled g5-falcon`, Get 0xE8 unsupported, Get D6 `0/0` (stock behaviour). **Confirmed.**
- Consequence for the staged plan: every later image needs a higher number (p3a 1030.0, p3b 1031.0, p3c 1032.0).
  Going back to stock after p3c needs a stock restamp above 1032 (for example 1039.0).
- Next: p3a by USB (not started).

## 0.7 Mac side (2026-11-24, `ssh mac-runner`, read-only)

- `monitor-ddc` builds and runs on the Mac (macOS 27.0.1, Apple Silicon). The 34" on the MacBook's **native HDMI**
  opens as `standard` protocol 3 with the **same MonitorId as on the PC**; Gets work, only the capabilities read
  returns NoReply. EDID product on HDMI = `0x7119` (**confirmed**, was inferred). PC and Mac agree on the 34"'s input
  and on `shows_this_host` (false on the PC, true on the Mac while it shows HDMI).
- The G5 on the **USB-C→HDMI adapter** (USB-PD VID 0x057E / PID 0x2003, DPCD branch OUI 00-10-FA `cHDMIb`) has no
  DDC/CI: every write to 0x37 fails (`IOAVServiceWriteI2C`, IOReturn `0xe0114102`, 20/20), while reads at any I2C
  address return EDID bytes, i.e. the converter emulates an EDID ROM and does not bridge DDC (**confirmed** by
  probes; mechanism inferred). No software path exists (`IOAVServiceGetDevice` is NULL; DPCD only reaches the
  adapter). Desk reports it as listed but unreachable.
- Consequence: the PC (DP) stays the owner of G5 control; a Mac fallback for the G5 needs a different adapter that
  bridges DDC (VMM7100-class, test before keeping) or the G5 on the native HDMI port.

## 1. What Tandem needs, as firmware features

Target: **protocol 3**, the same VCP layout and event ids on both monitors, so Tandem uses one driver and only the
profile (data) differs.

| # | Feature | Tandem use | Must / nice |
|---|---|---|---|
| F1 | Truthful Get 0x60 (the input shown, not the queried port) | know which computer owns each monitor | must |
| F2 | Switch input with a verdict (done / failed: no picture on target) | never leave the user on a black input | must |
| F3 | Power off by command (D6 = 4/5) | turn off monitors when the workstation idles | must |
| F4 | Power **on** by command from soft-off and from standby (D6 = 1) | wake from either computer | must, if physically possible (see §3, R1/R2) |
| F5 | Event ring: input changed (DDC or OSD), signal lost/present, power state, switch verdict | react instead of polling | must on 34" (done), nice on 32" (polling can replace it) |
| F6 | Capability word (one Get) | the crate knows what this monitor can do without guessing | must for protocol 3 |
| F7 | Signal present on the **inactive** input | refuse to switch to a computer that is asleep / unplugged | nice |
| F8 | "Source detection: auto" readable and forceable to manual | stop the monitor switching inputs by itself under Tandem | must (setting map), firmware only if no DDC path |
| F9 | Safe production image: no memory write / function call codes, or locked behind an unlock sequence | a bug in a host cannot brick or corrupt the monitor | must on 32" |

Not needed from firmware: identity (EDID hash in the crate, ADR-0018), arbitration between Mac and PC (policy: the PC
owns DDC; one master at a time because the request buffer is shared, `inactive-hdmi-ddc.md`).

### Protocol 3 layout (proposal; ADR to write)

- Keep 0xEA..0xEF exactly as protocol 2 (ring, cursor, live state 0xEE). The crate's probe stays valid.
- Get 0xEA ML = `3`. New **capability word** on a free manufacturer code (pick from the ADR-0008 range after
  checking both stock Get tables; candidate 0xE8 or 0xEF reuse) with bits: real-input, switch-verdict, events,
  power-wake, inactive-signal, source-detect, memory-access.
- New event ids: `0x14` power-state (0 off, 1 on, 2 standby/no signal, with cause DDC / button / DPMS), `0x15`
  signal-on-input (port, present). Old ids unchanged; clients ignore unknown ids (existing rule).
- Memory access codes (0xF0..0xF6) become **optional**, reported by the capability word, and absent from the G5
  production image (F9). The G5 dev hook codes stay only in dev images, which the crate never treats as protocol 3.

## 2. Phases

Each phase ends with something Tandem can use; no phase depends on the riskiest one (G5 code patch).

### Phase A — Measure both monitors (read-only plus input/power Sets; no flash) — 1 session, user present

Every test that changes input or power reverts automatically; the user can lose the PC picture.

1. G5: identify the running image (OSD version; Get 0xF2 for the dev magic `EF DE BE AD`). Record it.
2. Both monitors, from the PC over DP and from the Mac over HDMI, with each input active in turn:
   Get 0x60 (F1 truth), Set 0x60 with 0x0F/0x09/0x10/0x03 (G5 DP value), time to picture.
3. Power matrix, both monitors, for three states: **standby** (no signal, DPMS), **soft-off by D6=4/5**, **soft-off
   by the power button**. In each: does EDID still read? does DDC/CI answer *fresh* (D6 / 0x10 with a changed value
   check, never trust one reply)? does Windows keep the DP display handle (DP hot-plug drop)? does D6=1 wake it?
   does a video signal wake it?
4. OSD "Source detection" (auto/manual) and "auto power off" settings: locate them (`map-setting` on the 34").
5. Output: capability matrix in `docs/targets/*/overview.md` + both monitor profiles. This decides F4's route.

### Phase B — Tandem works on both monitors with no new firmware — client only

**Done (crate, 2026-11-23):** `profile.rs` (G5 profile as data, read-only EDID + capabilities match),
`ProfiledMonitor` (polled input, `switch_input` → `Accepted`), `open()` choosing standard / profiled / not
compatible / no channel, `FakeMonitorConfig::g5()` personality, tests in `tests/profiled_monitor.rs`, example
`examples/desk.rs` verified on the real desk from Windows. **Left:** Tandem adopts `open()` and the new verdict;
power through DPMS from the owning computer.

- Crate `monitor-ddc`: profile per model (data), driver chosen by Get-only probe: `mfw-proto` (34" today) and
  `mccs-polled` (32" stock). For the 32": if Phase A shows Get 0x60 is truthful, poll 0x60 + D6 every ~1 s and
  **synthesize** input-changed and switch verdict (confirmed by reading 0x60 back), so Tandem gets F1/F2/F5 without
  touching the G5 firmware.
- Power: D6 off on both; wake through whichever path Phase A proved (D6=1, or DPMS: the owning computer wakes its
  output and the monitor follows the signal).
- Two-monitor FakeBus tests (one patched, one stock), hot-plug, "no vendor code before probe".
- Exit: Tandem switches and powers both monitors from either computer; the 32" reports `input_truth = polled`.

### Phase C — 34" patch v3.2 (protocol 3) — MStar, proven route

1. RE (static, `re-query`): stock D6 path (`FUN_0026c1ad`, power-off `0x26f620`), the power-key handler, and what
   the main loop still runs while `cfg[0xd7]` bit0 is clear (is our poll hook alive in soft-off?).
2. If the AP keeps running in soft-off: Set D6=1 in `sethook` calls the stock power-on path (same function the key
   uses). If the AP stops, F4 on the 34" is only "wake by signal": document and skip.
3. Add event 0x14 / 0x15, capability word, source-detect exposure (F8). Stretch: inactive-port signal (F7) needs the
   HDMI RX clock-detect register of the inactive port; only if found in bytes.
4. Per site guards in `versions/1006.0.toml`, golden listing, FakeMonitor tests, `docs/protocol/` + CHANGELOG.
5. `build-image` → `flash-monitor` (user's go-ahead in session, verified backup) → `hil-check` including the
   30-minute standby/wake item.

### Phase D — 32" production patch (protocol 3 on Novatek) — longest, gated

Only after Phase B works, so Tandem never waits on it.

1. Baseline: back to stock 1008.3 by USB (if bank A holds a dev image) and a fresh full SPI read kept as the permanent
   backup (already have `bootA.bin`; one more read after the USB flash).
2. RE of the SPARC main app (Ghidra project `data/ghidra-g5`): Get/Set VCP jump tables, the input-switch function
   and the "shown input" variable (F1), the D6 handler and power-state machine, and **verified-free RAM** for the ring
   (the 1019.0 slots overlapped a live settings table: prove free RAM by snapshots across OSD use, reload and
   standby).
3. Implement protocol 3 as a new `final_hook.py` build: 0xEA..0xEF ring, truthful 0x60, verdict, power events,
   capability word; **no** memory write or call codes (F9). One feature per image.
4. Staged USB flashing exactly as `overview.md` "Recovery and risk": stock → data-only → one code feature at a time.
   SPI clip connected-ready as recovery. Never the DDC flasher.
5. F4 on the 32": the stale-reply observation says the SPARC DDC service is not running in standby. Wake by DDC
   would need the 8051 standby loop to watch DDC/CI; this is **research**, not committed scope. Default: wake by
   signal.

### Phase E — Integration and soak

- Tandem test matrix: 2 monitors × 2 computers × {switch, power off, wake, OSD change, cable unplug, standby} with
  auto-revert, recorded in Tandem's TESTING.md and here.
- 24 h soak: event ring has no gaps, no stale replies, no DXVA handle loss after standby.
- Release: tag both firmware versions, update `tandem.md`, ADR for protocol 3, Tandem `DESIGN.md §8`.

## 3. Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | **Confirmed for the DP host (2026-11-23).** **Wake by DDC is physically impossible** on one or both: in soft-off the scaler stops the DDC/CI service (G5 standby already returns stale replies) | high / F4 lost | Phase A decides; fallback: wake by signal (DPMS) from the owning computer, button for true off. Do not promise F4 before Phase A |
| R2 | **Confirmed on the 34" (2026-11-23).** DP hot-plug drops when the monitor turns off, so Windows loses the DXVA2 handle and cannot even send D6=1 | medium / F4 from PC lost | Measure in Phase A; then try from the HDMI side, or wake by signal |
| R3 | Brick of the G5 during flashing | medium / days lost | USB updater only (proven), staged images, A/B tag behaviour, SPI clip recovery (proven 2026-11-22), full SPI read before each step. DDC flasher banned for this plan |
| R4 | Brick of the 34" during ISP flash | low / high | Verified backup, never below 0x11000, `restore-stock` skill, per-sector flash (ADR-0014) |
| R5 | VCP code collision: a host sends 34" codes to the 32" dev hook (memory write / call) | medium / corruption | Get-only probe before any vendor code (crate already does this); protocol 3 capability word; G5 production image has no memory codes (F9) |
| R6 | G5 hook RAM overlaps live data (happened with 1019.0) | medium / settings corruption, crashes | Free-RAM proof by snapshots across OSD/reload/standby before using any RAM |
| R7 | Stale DDC replies read as truth (standby, busy after a call) | high on 32" / wrong state in Tandem | Freshness check (changed-value read or two different codes in a row), already in `g5-ddc.ps1`; port it to the crate |
| R8 | Shared DDC request buffer: Mac and PC talk at the same time → mixed replies, lost event cursor | medium / wrong verdicts | PC is the only DDC master; Mac goes through Tandem's control plane (tandem.md §1) |
| R9 | Monitor switches input by itself ("Source detection: auto", auto power off) and fights Tandem | high / confusing UX | Map the setting (Phase A/C), force manual through DDC when possible, show it in the UI |
| R10 | Get 0x60 on the stock G5 is not truthful → polling cannot replace the patch | medium / 32" stays `tracked` until Phase D | Phase A answers it; Tandem already handles `input_truth = tracked` |
| R11 | Samsung's official updater or a future firmware overwrites the patch / version drift | low / features lost | Version maps + guards refuse unknown versions; `port-firmware-version` skill; keep stock images |
| R12 | G5 SPARC RE is large (no symbols, relocated HAL) | high / Phase D slips | Phase B makes Tandem independent of it; one feature per image |
| R13 | Serial or vendor bytes leak into git / Tandem repo / issues | low / legal + privacy | `test_repo_hygiene.py`, EDID-hash ids only, data in `data/` and `out/` |
| R15 | An input switch or wake makes a monitor appear/disappear for the Mac, which re-arranges displays (both black for seconds; mirroring changes) | high (seen 2026-11-23) / confusing UX | Tandem switches one monitor at a time, waits for macOS to settle, and keeps the Mac's display layout (or re-applies it) |
| R16 | **The 34" firmware hangs when the PC turns its displays off** (no DP signal) **with OSD "Auto Source Switch" ON**: no LED, no DDC, button dead, still listed; only a power-cable cycle recovers. Reproduced twice with no DDC client; with the setting OFF it woke correctly twice (2026-11-23) | high with the setting on / monitor unusable until unplugged | **Keep Auto Source Switch OFF** (settings `0x14f` = 1; also stops the monitor switching by itself). Root cause (stock vs v3.1) open: compare with stock 1006.0. Tandem must warn if it reads `0x14f` = 0 |
| R17 | dxva2 calls to the G5 block for tens of seconds while it boots, and `Desk::scan` is sequential | high / every monitor's events late during that time | Never re-read capabilities of a known unit (done); Tandem runs scans off the UI thread; later: per-monitor locking in the Windows backend |
| R14 | Branch drift (`g5-falcon` vs `develop`) breaks the crate or the client | medium / merge pain | Merge `develop` into `g5-falcon` (or rebase) before Phase B |

## 4. Decisions needed from the user

1. Protocol 3 as one common layout for both monitors (recommended), or keep per-monitor drivers.
2. G5: keep the current bank A image (it works with the profile) or return to stock 1008.3 before Phase D.
3. Wake: Phase A showed DDC wake from the DP host is impossible today. Choose: wake by video signal (no firmware),
   try DDC from the Mac's HDMI in standby (one test), or a Phase C patch that keeps DP alive in standby.
