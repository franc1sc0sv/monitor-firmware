# G5 (FALCON): Tandem features, firmware evidence, production patch and HIL runbook

Static analysis of the stock **M-C5500GGZA-1008.3** image (the local copy under `data/vendor/g5/stock-1008.3/`), the
production patch built from it (`firmware/targets/g5-falcon/patches/production_hook.py`), and the runbook for the
hardware session. p3c ran on the monitor on 2026-11-24 (results in section 7); p3d is built, not flashed. Confidence per ADR-0001: **confirmed** = read in the
disassembly or bytes of this image (or an earlier hardware observation quoted from `firmware-re.md`); **inferred** =
reasoned from them.

> **Second pass, 2026-11-23.** The first version of this page had three errors, now fixed: (1) it said Set 0xD6 is
> never compared by the stock handler (it is, see Goal 1); (2) it had the `SecLibPower_SetPowerState` argument
> values wrong and called `0x10345C` a power actuator (it is the boot-time power init); (3) it called the BSS gap
> at `0xA803C3E8..0xA803D000` free RAM (it is the C library heap's address range, see "RAM").

Address convention (as in `firmware-re.md`): SPARC code addresses are **nominal VAs**, file = VA + `0x2E000`; data
file = VA + `0x2DD00`. The code record has a 0x320-byte header, so code runs at VA + 0x320: absolute pointers in
tables hold VA + 0x320 (the Get jump table is at nominal `0x184C0C`, not `0x184F2C`), relative calls are unaffected.

## 1. What the firmware does (evidence)

### Main loop and context (confirmed)

The kernel in the HAL record (SRAM `0xA0028000`) runs the main loop at `0xA00295D8..0xA00295F8`: it calls, in order,
`0x18C03C`, `0x162DEC`, `0x177C2C`, the SecApp handler `0x17BFEC` (app event loop `0x17AD04`, no-sync OSD
`0x17FAA8`, `__DpmsHandler` `0x17B778`) and `0x104718`, a thunk to the **DDC/CI dispatcher `0x103DBC`**. So the DDC
handlers run in the same main-loop context as the DPMS handler and the off timer, not in an interrupt.

### Goal 1: power

- **Stock Set 0xD6 (confirmed):** `DddCmdSetVcp` (`0x1869BC`) handles 0xD6 at `0x186C7C`: values 1 and 2 are
  accepted and do nothing; value 4 sets bit 30 of the flag word `0xA803B0D4`; value 5 is unsupported. A scan of every
  access to `0xA803B0D4` finds the same set at `0x1857FC` and **no reader of bit 30**: the request is recorded and
  never acted on. This is why D6 = 1/4/5 did nothing on hardware. Get 0xD6 goes to a "supported, zero" target
  (`0x188304`), hence `0/0`.
- **Power state machine (confirmed):** `SecLibPower_SetPowerState` (`0x1ADACC`): 0 toggle, **1 off** (`[Power]
  OFF:DC`: saves the off state, LED off, `SetSystemPowerState(1)`), 2 on, **3 power saving** (`OFF:DPMS`), 5 wake.
  It stores the state in `0xA8034D88` through `0x18BDCC`. Callers: the app action dispatcher `0x1798C8`
  (`SECAPP_APPATN_PWR_ONOFF/OFF/ON/SAVING`), `__DpmsHandler` (3 and 5), the cable poller (5), and the **off timer
  `SecLibPower_OffTimerHandler` (`0x1ADFEC`), which calls it with 1 and nothing else**. `0x10345C` / `0x1035D0` are
  the boot-time init by boot cause (called once by the kernel), not a runtime actuator.
- **DDC power events look disabled in this build (inferred):** the event tables name `SECAPP_APPEVT_DDCCI_PWR_ON /
  OFF / SAVING` (confirmed), and the event-to-action map at `0x206580` appears to send them to "ignore".
- **In standby and off the SPARC stops (mailbox hand-off confirmed in `firmware-re.md`; matches the stale replies seen
  on hardware):** power
  saving and power off end in HAL mailbox commands 0x16 / 0x17 with mode 3 (spin forever); the 8051 takes over and
  restarts the SPARC on a wake event. The wake causes the SPARC reads back are power key, left/right key, cable
  unplug, and another source's cable plug (`0x124184..0x1242E4`, `0x1777CC`). There is no DDC wake among them.
- **No vendor "fake DPMS" (confirmed):** `SecHalScaler_SetFakeDPMS` (`0x124334`) is an empty stub and
  `IsFakeDPMSOn` (`0x12433C`) returns 0 on this model.
- **Panel control (confirmed by its own strings):** `SecLibCommon_PanelOnOffControl(onOff, force2Finish)`
  (`0x18BDE8`) -> `SYSAPI_PanelOnOffControl` (`0x16CA98`), the panel power sequencer; with force 1 it waits for the
  sequence to finish. The stock power-off uses the same primitive with (0, 1). LED routines: `0x18A710`
  (`SecLibCommon_LedOn`), `0x18A830` (`SecLibCommon_LedOff`), no arguments: the key LED, not the backlight.

Consequence: power **off** by command is one stock call. Power **on** by command is impossible once the SPARC has
stopped, so the only DDC wake is a **soft standby** that never stops it: panel sequence off, LED off, everything else
running. Whether the main loop then leaves the panel off (and whether the sequencer also turns the backlight off) is
**inferred** and is the main question of stage p3b.

### Goal 2: input, signal, events

- **Get 0x60 is truthful in stock (confirmed):** the handler (`0x189634`) calls
  `SecLibSource_GetCurrentSecSourceName(0)` (`0x1B02C0`): `0x10` = DP1, `0x00` = HDMI1. Stock Set 0x60 (`0x186CD0`)
  takes `0x0F` (DP) / `0x11` (HDMI) and calls the source change `0x1B0500` directly from the DDC context.
- **Picture locked (confirmed):** the main window's sync state is the word at `0xA803B12C`, written by
  `SecHalScaler_UpdateSyncState_CallBack` (`0x123620`): 0 none, 1 no sync, 2 has sync / mode search, 3 locked but out
  of range, **4 locked** (`SEC_SYNC_SYNC_NORMAL`). The accessor `0x18C678` has 75 callers.
- **Cable per input (confirmed):** the main-loop poller `0x18CA84` keeps `u32 cable_state[2]` at `0xA803B13C`
  (previous values at `0xA803B134`): **2 = connected, 1 = not**, from `SecHalScaler_IsCableConnectedBySourceName`.
  Index 0 = HDMI1, index 1 = DP1 (source table at data `0x2098CC`). This is cable detect, not link clock; a per-source
  clock table exists at `0xA803B180` (not used by the patch).
- **Time base (unit inferred):** `0xA8037D2C` is incremented by one in `__DpmsHandler` (`0x18FD80`) and wraps at
  86400: a seconds counter. The patch reports it x100 in the 10 ms fields, so times have 1 s steps and wrap daily.
  The crate tells that wrap from a reboot by the host's own elapsed time and the sequence (`daily_wrap` in
  `crates/monitor-ddc/src/protocol.rs`), so the wrap is not reported as `rebooted`.
- **Codes:** Get 0xE8 and 0xEA go to the "unsupported" target `0x188300` in stock (free). Get 0xEB..0xEF and Set 0xEB
  **have stock Samsung handlers** (0xEB is a service escape with a sub-command table); the ring shadows them.

### Goal 3: inactive input and auto source

Cable presence of the inactive input comes from the table above (capability bit 4, event 0x15). Auto source exists
(`SecLibSource_AutoSourceSwitchHandler` `0x1B1934`, `SECAPP_OSD_AUTO_SRC_EVENT`); the cable poller calls the wake when a
source's cable state changes in power saving (which source: inferred, the current one). Whether a switch to a connected but silent input
hops back by itself is **not decided statically**; the HIL run measures it (p3c, test 6). The source-detection
setting is not located yet, so capability bit 5 and flag bit 1 stay 0.

### Goal 4: DDC during boot

The only DDC/CI responder is the SPARC dispatcher in the main loop (confirmed above); the frames live in a mailbox
buffer shared with the 8051 (`firmware-re.md`). While the SPARC boots, nothing services requests: **inferred** cause
of the tens-of-seconds stalls and of the stale frame in standby. A SPARC patch cannot answer before the SPARC runs;
answering from the 8051 would mean patching the 8051 runtime, which this plan does not touch. Mitigation stays in the
client (ADR-0020: never re-read capabilities of a known unit).

## 2. RAM: the "free gap" is the C heap (confirmed)

`0x1EEE68` is the C library `sbrk`: break pointer at `0xA803C0A0`, heap start `0xA803C0A8`, no upper limit. Its only
caller is the allocator (`0x1EE490`), reached from C library formatting code (which callers reach it at runtime:
not traced). So `0xA803C0A8..0xA803D000` is unreferenced by
name but **belongs to malloc**. Dev images 1020.1..1021.4 wrote all over it (slots at `0xA803CFC0`, uploads from
`0xA803C400`) without visible damage, and the slots read 0 after boot, which suggests malloc is not used in normal
operation (inferred). No statically proven free RAM is known.

What the patch does about it: state (16 bytes at `0xA803CFC0`) and ring (512 bytes at `0xA803CDC0`) sit at the top
of that range, and every entry that touches RAM first reads the break pointer. **If the heap has grown above
`0xA803CDC0` the hook does not read or write its block and hands every code to the stock handler** (the monitor then
behaves like stock: Get 0xEA unsupported). The symptom on the bench is "protocol 3 disappears"; it means the block
must move. p3a uses no RAM at all.

## 3. The patch (`patches/production_hook.py`)

Two call redirects in the dispatcher (Get `0x103EBC`, Set `0x104170`: the sites every dev image used) into dead
code. The boot path and every other stock byte are unchanged; the hook runs only when a host sends Get/Set VCP.

| Stage | Version | Adds | Capability word (CH:CL) | Code regions used |
|---|---|---|---|---|
| p3a | 1030.0 | Get 0xE8, Get 0xD6 = 1, Set 0xD6 = 4 or 5 -> `SetPowerState(1)` | `0x0091` | main 0xB8/0x280, leaf 0x30/0x90 |
| p3b | 1031.0 | soft standby: Set 0xD6 = 4 panel off + LED off, 1 = panel on + LED on, 5 = power off; Get 0xD6 = 4 in soft standby; 0xE8 ML bit 0 | `0x0099` | main 0x1C4/0x280, leaf 0x30/0x90 |
| p3c | 1032.0 | ring 0xEA..0xEF (protocol 3, size 0x40), events 0x00 0x01 0x06 0x10 0x11 0x12 0x14 0x15, switch guard | `0x019F` | main 0x244/0x280, aux 0x114/0x114, sample 0xFC/0x114, leaf 0x84/0x90 |
| p3d | 1033.0 | p3c with the soft standby done by the backlight alone: Set 0xD6 = 4 -> `SecHalBoard_SetBacklight(0)`, 1 -> `SetBacklight(1)`; no panel sequencer call (section 7) | `0x019F` | main 0x22C/0x280, others as p3c |

Capability bit 6 (memory codes) is 0 in every stage; there is no memory, call or SPI code. Bit 5 is 0.

- **Regions.** `main` `0x1E14EC` (0x280) and `leaf` `0x1E45D4` (0x90) were hook space in the dev images
  (hardware-proven dead). `sample` `0x1E176C` and `aux` `0x1E1AE4` (0x114 each, **p3c only**) are dead by a static
  test only: no call from the app or the HAL record, no pointer word anywhere in the image, no address
  materialisation, no branch from outside. That test is not a proof (firmware variants keep unused functions, and
  it cannot see a computed call), so p3c carries more risk than p3a/p3b.
- **Watchers run when the host polls.** There is no main-loop tap: Get 0xEA and Get 0xEE sample the port, the sync
  state and the cable mask and log what changed since the last poll; the pending switch gets its verdict there too
  (done = target on screen and sync state 4; failed = 8 s on the seconds tick). A state that changes and changes back
  between two polls is not logged. The first poll after boot logs `boot` and each value with old = `0xEE`.
- **Set 0x60** (p3c): logs 0x10 (old = port on screen, new = requested value), then either refuses a target whose
  cable bit is clear (0x12, old = target, new = current; the stock handler is not called) or arms the verdict and lets
  the stock handler switch.
- **Set 0xD6 = 5** calls `SetPowerState(1)`, the off timer's call. Expect the monitor to stay off until the **power
  key** (the off state is saved like a key press): inferred.
- **Differences from the protocol text, to settle after HIL:** soft standby does not mute audio; the power key in soft
  standby is the stock toggle, so it powers the monitor off instead of ending the soft standby, and no `0x14` with
  cause 2 is logged; event times have 1 s resolution; 0xEE ML is always 0.

Guards: `versions/1008.3.toml` holds the whole-image hash plus SHA-256 guards for both call sites, the four regions,
every stock routine the hook calls or returns into, and the code that proves each RAM meaning (cable poller, sbrk,
tick, sync callback, source table). The builder refuses any other base image.

Tests (`tests/test_g5_production_hook.py`): the generated machine code runs in a small SPARC interpreter written
separately from the encoder, with the firmware routines stubbed: pass-through of every other code in the caller's
window, capability word, D6 paths, soft standby, heap interlock, ring layout as the Rust `StandardMonitor` reads it,
verdicts, guard, wrap. This checks the hook's logic, not the firmware's behaviour.

Build (images go to the ignored `out/g5/`; the file name is what the USB updater checks):

```bash
uv run python firmware/targets/g5-falcon/patches/production_hook.py \
    data/vendor/g5/stock-1008.3/extracted/"M-C5500GGZA-1008.3[C145].img" --out out/g5
```

## 4. What stays inferred until the HIL run

1. `SetPowerState(1)` from the DDC handler powers off cleanly (same context as the off timer: confirmed; the result on
   screen: not yet seen).
2. Panel off through `PanelOnOffControl(0, 1)` also turns the backlight off, stays off while the main loop runs, and
   comes back with (1, 1); DDC keeps answering; the DP link stays up for the PC.
3. The LED routines give "standby" and "on" looks.
4. malloc is not used in normal operation (heap break stays 0).
5. `sample` and `aux` are dead code.
6. The tick is seconds. The cable table follows the cable within about a second, also for the inactive input.
7. The 8 s verdict window suits this monitor's switch time (measured 1-2 s on stock).

## 5. HIL runbook (user present; one stage per session step; never the DDC flasher)

Rules: flash only with the user's go-ahead in that session, only by USB stick, files copied with native Windows to a
FAT32 stick with a single `.img` in the root. Keep the stock `M-C5500GGZA-1008.3[C145].img` on a second stick and the
SPI programmer (CH341A + clip, backup `data/dumps/g5-offboard/bootA.bin`) within reach before the first flash.

**If a patched image misbehaves** (reboot loop, black screen when a computer is connected): the hook only runs on
DDC traffic, so **unplug both video cables**, power-cycle, and re-flash stock 1008.3 from USB. If the monitor does
not start the updater even with no cables, restore by SPI clip (procedure of 2026-11-22). Stop the run and record
what was sent last.

0. **Baseline.** Read the OSD version (bank A's image was never recorded). If it is not 1008.3, flash stock 1008.3 by
   USB and confirm the OSD shows it. Run `desk status` (crate example `crates/monitor-ddc/examples/desk.rs`): the G5
   must be `profiled g5-falcon`. Take a full SPI read as the permanent backup if the clip is already on.
1. **p3a** `M-C5500GGZA-1030.0[BFFA].img`. Expect OSD 1030.0.
   - `desk status`, `desk switch g5 dp`, `desk switch g5 hdmi`: exactly as stock (still `profiled`, `Accepted`).
   - Brightness and contrast reads/writes unchanged (any stock code).
   - Get 0xE8: MH = 3 with both cables, `0091` in CH:CL. Unplug the HDMI cable: MH = 1 within a few seconds; plug it
     back. Repeat with DP from the Mac side if possible. Get 0xD6 = `0005/0001`.
   - Set 0xD6 = 5: the monitor powers off (LED as after the power key). Check what wakes it: power key (expected),
     video signal, cable re-plug. Record it. Repeat with Set 0xD6 = 4 (same result in this stage).
   - Leave it running 30 minutes with the PC in normal use: no reboot, no OSD glitch.
2. **p3b** `M-C5500GGZA-1031.0[C0D3].img`. Expect OSD 1031.0.
   - Everything from p3a again (Get 0xE8 CH:CL = `0099`).
   - Set 0xD6 = 4: picture and backlight off, LED off, **Windows keeps the display** (no device-removed sound), Get
     0xD6 = 4, Get 0xE8 ML = 1, Get 0x10 still answers fresh. Watch 5 minutes: does the panel stay off? Does moving
     the mouse, an OSD key, or an input change turn it back on by itself? Record each.
   - Set 0xD6 = 1: picture back within the panel sequence time, Get 0xD6 = 1.
   - In soft standby: press the power key once (expected: real power off), then again (expected: on, not in soft
     standby). In soft standby: let the PC blank its displays (expected: stock standby, wake by signal).
   - In soft standby: Set 0xD6 = 5 (expected: power off).
   - If Get 0xE8 stops answering at any point, the heap interlock tripped: note what was on screen and stop.
3. **Free-RAM proof before trusting p3c.** With p3b installed, use the monitor normally for a day (OSD menus, every
   picture mode, input changes, standby and wake, a cold boot) and check after each activity that Get 0xE8 still
   answers and soft standby still works: both go through the interlock and the state block. If a dev image is ever
   flashed again, read `0xA803C0A0` after the same activities (0 = malloc never ran). p3c is trusted only if the
   interlock never trips.
4. **p3c** `M-C5500GGZA-1032.0[B260].img`. Expect OSD 1032.0.
   - `desk status`: the G5 opens as `standard` (protocol 3), capability word `019F`.
   - `desk watch 60`: first poll shows boot + initial values; then silence while nothing changes.
   - `desk switch g5 hdmi` and back: `Confirmed` with `switch-done`; time it. Change the input with the OSD: an
     `InputChanged` not caused by this host.
   - Unplug the HDMI cable: cable-mask event; `desk switch g5 hdmi` now fails at once (`switch-failed`, picture
     stays). Plug it back.
   - Switch to an input whose computer is asleep (cable in, no picture): `switch-failed` after about 8 s; note
     whether the monitor hops back by itself (Goal 3).
   - Soft standby and wake by the desk API: `PowerChanged` both ways.
   - Read 0xEF twice 10 s apart: difference 1000 (confirms the seconds tick).
   - 24 h soak with `desk watch`: no gaps in the sequence numbers, no reboot.
5. **Record** every result in `overview.md` and here, change "inferred" to "confirmed" or to what was seen, and only
   then update the G5 profile in the crate.

6. **p3d** `M-C5500GGZA-1033.0[B515].img` (over p3c by USB; 1033.0 > 1032.0). Expect OSD 1033.0.
   - `desk status`: `standard`, capability word `019F`; one switch each way still `Confirmed`.
   - Set 0xD6 = 4: screen dark at once (no panel power-down delay), Windows keeps the display, Get 0xD6 = 4, event
     0x14 new = 4. Look at the panel in a dark room: no glow at all = backlight off (expected).
   - Set 0xD6 = 1: **picture back within a second**, Get 0xD6 = 1, event 0x14 new = 1. Repeat five times, and once
     after 10 minutes dark.
   - In soft standby press the menu key: the stock firmware is expected to relight the screen for the OSD by itself
     (Get 0xD6 still says 4: known gap). Then Set 0xD6 = 4 again: dark again. Then Set 0xD6 = 1.
   - In soft standby `desk switch g5 hdmi`: expected `Confirmed` **and the screen relit by the stock firmware** (same
     gap). Record what happens.
   - In soft standby: power key (expected real power off, then on with picture), PC display sleep (stock standby, wake
     by signal with picture), Set 0xD6 = 5 (power off).
   - If the wake leaves the screen dark: do not power-cycle yet. Run the "no flash" experiments of section 7 first.

## 6. Open work after HIL

- Source-detection setting (bit 5, flag bit 1): find it through the settings accessor `0x1B5CE4(index)` and the OSD.
- Audio mute and power-key handling in soft standby (needs a main-loop tap; one more region).
- p3d: Get 0xD6 / 0xE8 keep saying "soft standby" after the stock firmware relights the screen by itself (key, input
  change). Fix candidate: report soft standby only while `SecHalBoard_IsBacklightOn` (`0x1179B0`) is false (about 0x30
  bytes of `main`; 0x54 are free in p3d).
- Finer time base than one second, if Tandem needs it.
- A RAM home outside the heap, if the interlock ever trips.

## 7. p3c on hardware and the wake fix (2026-11-24)

### Seen on the monitor with p3c (confirmed, hardware)

- Protocol 3 works: Get 0xEA = `0x4003`, Get 0xE8 = `0300/019F`, DP <-> HDMI switches `Confirmed` in about 2 s, event
  ring, cable mask.
- Set 0xD6 = 4: picture gone, Get 0xD6 = 4, event 0x14 logged.
- **Set 0xD6 = 1 does not bring the picture back.** The call returns, Get 0xD6 = 1, the event is logged, the sync
  state is locked (0xEE CL = 1), the screen stays black and the OSD does not show on the menu key. Twice.
- A DDC switch (Set 0x60) in that state is `Confirmed` and the screen stays black.
- Changing the input with the monitor's keys brings the picture back.

### What the firmware does (confirmed in the disassembly unless marked)

- **Panel sequencer.** `SYSAPI_PanelOnOffControl` (`0x16CA98`) drives a state byte at `0xA803AD20` through the step
  function `0x16978C`: 1 = off, 2..5 = on steps (panel power GPIO, transmitter, wait), 6 = on, 7..9 = off steps. With
  force = 1 the caller loops until 6 (on) or 1 (off), so p3c's `PanelOnOffControl(1, 1)` did run to "on".
- **The on steps do switch the backlight on**: step 5 -> 6 ends in the backlight leaf `0x1505C4` (HAL GPIO 6/0x80 = 1,
  then the PWM gate `0x16367C`). The panel power GPIO (5/0x10) is set in step 2.
- **The off steps do more than the on steps undo.** Step 7 (`0x1699A8`) calls `0x138E68(0, 0, 0, 0)`: it puts display
  channel 0 into forced-colour output (scaler register 0x54 = 2) and, for channel 0 only, reprograms the output timing
  for free run (`0x136BE4` and four clock writes `0x1370B4`). No on step reverses either. The stock inverse of the
  forced colour is `Display_ShowNormalImage` (`0x138FB8`, register 0x54 = 0), reached only through
  `SecHalScaler_SetVideoMute(window, off)` (`0x11DBFC`) and the window state machine (`0x166208`), with the window's
  own channel number.
- **Stock never needs that inverse.** `SecLibPower_SetPowerState` does not call the sequencer for "on" (2) or "wake"
  (5): they set flags and the stored state. `SecHalScaler_SetSystemPowerState` (`0x124344`, reached through `0x18BDCC`)
  calls the sequencer only with "off", right before the SPARC stops. The panel comes on in the boot path (init step
  `0x18C168`: `PanelOnOff(1, 0)`, then the boot's own backlight call) on a freshly initialised scaler. The only stock
  "on" calls at run time are `SecLibCommon_PowerOnPanelForOSDDisplay` (`0x18BE40`) and one service command
  (`0x1A2750`), both only when the panel is not already on.
- **Backlight at run time.** `SecHalBoard_SetBacklight(on)` (`0x1179C8`): on = `0x1505C4`, off = `0x1505E4` (PWM gate,
  then GPIO 6/0x80 off). `SecHalBoard_IsBacklightOn` (`0x1179B0`) and `IsPanelOn` (`0x117B00`) read the two GPIOs.
  Every source change (`0x1B0500`, the function stock Set 0x60 and the OSD both call) starts with
  `SetBackLightOff` (`0x11DED8` -> `0x117DE4`), from the DDC context too. After the new picture is shown,
  `__APPTasksAfterDisplay` (`0x1791E0`) calls `SetBacklight(1)` (through `0x1A756C`) if the panel power GPIO is on and
  the backlight GPIO is off. `Display_ShowNormalImage` only restores the backlight state it found. A scan of every
  direct call finds no periodic caller of the backlight leaves.
- **Key path.** The app action handler (`0x179C74`) calls `PowerOnPanelForOSDDisplay` when the backlight GPIO is off;
  with the sequencer already "on" that is `SetBacklight(1)`. The OSD source select then calls the same `0x1B0500` as
  the DDC handler (plus saving the setting).

### Root cause of the black wake: not settled statically

Confirmed: the run-time "panel off, panel on" pair is not symmetric in this firmware and stock never uses it that
way; p3c's wake is a path the vendor code does not exercise. **Inferred**, two candidates that the disassembly cannot
tell apart:

1. Display channel 0 stays in forced black with free-run timing after the on sequence (backlight on, black frame,
   OSD covered). Against it: by the disassembly a DDC switch should then have shown a picture after its own unmute,
   unless the main window uses another channel number than 0 (run-time value, not read).
2. The panel or its transmitter does not restart cleanly from the free-run state the off sequence left (backlight
   on or off, nothing shown). Against it: nothing explains why a key input change repairs it and a DDC one does not,
   other than the key handler's extra `PowerOnPanelForOSDDisplay`.

Experiments on p3c that need no flash, in the black state after Set 0xD6 = 1 (each tells the two apart):
- Dark room: is there backlight glow? Glow = black frame (1). No glow = backlight or panel off.
- Send a second and a third DDC switch (DP -> HDMI -> DP). If the picture returns on a later switch, the key path
  was not special.
- Press only the menu key, wait 5 s, then send one DDC switch. If the picture returns now, the missing piece is the
  key handler's backlight call.
- Read Get 0x10 and set brightness: any visible change means the backlight is on.

### p3d: do not use the sequencer (the fix)

Soft standby in p3d is the backlight alone, with the two calls stock makes around every input change:

- Set 0xD6 = 4: `SecHalBoard_SetBacklight(0)`, `LedOff`, flag = 1. Not skipped when the flag is already 1.
- Set 0xD6 = 1 (only when the flag is 1): `SecHalBoard_SetBacklight(1)`, `LedOn`, flag = 0.
- Set 0xD6 = 5 and everything else: as p3c.

Why this is the safe choice: both directions are exercised by stock at run time on every switch (hardware: every
`Confirmed` switch ends with a lit picture), `0x1B0500` proves the off call is made from the DDC handler context, the
scaler, the panel power, the transmitter and the output timing are never touched, so there is nothing to restore.
Cost: the panel electronics stay powered in soft standby (the backlight is the large consumer; not measured).
Known gaps (inferred from the disassembly, to check in HIL step 6): a key press or an input change in soft standby
relights the screen (stock code) while Get 0xD6 keeps answering 4 until the host sends 1; a second Set 0xD6 = 4
darkens it again. Guards added: `set_backlight`, `backlight_gpio`, `backlight_pwm_gate`,
`source_change_backlight_off`, `after_display`, `panel_sequencer_off`.
