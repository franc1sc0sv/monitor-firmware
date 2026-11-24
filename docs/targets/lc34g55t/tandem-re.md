# LC34G55T: static RE for Tandem (power, DPMS hang, events, protocol 3)

Date 2026-11-23. Static analysis only (stock 1006.0 RAM image, the full flash dump, the analysed Ghidra projects and
a scratch 8051 project). Nothing was sent to a monitor, nothing was flashed, no firmware source was changed.
Addresses are real RAM addresses of 1006.0 unless marked `PM:` (8051 code address) or `flash:`.

Confidence (ADR-0001): **confirmed** = seen in bytes or disassembly in this session; *inferred* = decompiler output,
naming, or reasoning not yet checked in disassembly or on hardware.

## 0. The one fact that explains most of it: two CPUs

- **confirmed** The flash holds a second program: 8051 code ("PM51") at `flash:0x11080..0x1b92e` (base 0, reset vector
  at 0, Keil-style startup at `PM:0x27aa`). Base found by scoring LCALL targets that follow a RET (2060 of 3398 at
  this base, next best 583). `overview.md`/`journal.md` place the PM code at `0..0x10000`; that was the 1012.1 file
  layout, not this dump. A second, different copy sits in the B area from `flash:0x21100`.
- **confirmed** The AP (AEON) leaves the stage completely for both standby and power-off. `0x248f20` (called from the
  main loop at `0x26b6d7`, the instruction right after our poll hook at `0x26b6d3`) runs when the request word
  `0x4ca730` is 1 (standby) or 2 (off). It ends in `0x21387e`, which masks all interrupt groups (`0x2b08/18/28` =
  `0xffff`), writes a 20-byte request block from `0x4f82c0` to the mailbox registers `0x103380..`, sets `0x10181e` to
  1 and then **spins forever** at `0x2138d2` (`j` to itself). The 8051 is expected to cut the AEON off.
- **confirmed** PM51 reads that block (`PM:0x8fbd`, only when `0x10181e` reads 1) into XDATA `0x5935..`, and on wake
  writes 10 bytes of wake information from XDATA `0x592b..` back to the mailbox (`PM:0x8c1d`), then sets `0x10181e`
  to 2. The AP reads it at boot into `0x4f82d4..` only if `0x10181e` reads 2 (`0x21359b`).
- *inferred* (boot decompile, `data/ghidra-boot/boot.c`): waking is a full AEON boot (stage1, stage2, inflate), the
  same path as a cold boot. There is no resume from RAM.

Consequence: **in standby and in power-off none of our patch code runs** (no main loop, no timer ISR, no Get/Set
handlers), the event ring and the 2 KB block are lost (BSS is cleared at every boot), and every DDC reply comes from
PM51, not from the AP.

Request block (AP `0x4f82c0`, u16 LE each; *inferred* from `0x248f20` decompile): `+0` mode (1 standby, 2 off),
`+2` mask of the displayed port(s), `+4` inverted mask, `+0xa` cable-detect mask (`0x27cede`), `+0xc` setting
`0x20416b`, `+0xe` setting `0x204131` (power LED), `+0x12` source-detection manual flag (`0x20414f != 0`).
Wake block (AP `0x4f82d4`): `+0` wake status, `+2` wake port, `+4` wake key.

## 1. Power on by command

### Findings

| # | Finding | Confidence |
|---|---|---|
| 1.1 | Set `0xD6` (block at `0x270c5d` in the Set handler `0x270b45`): values 1 and 2 are ignored, **only 4 acts**, every other value (including 5) is ignored. Value 4 sets bit 2 of `0x4c1bfc` and calls the power-off routine `0x26f620`. (The journal's `DAT_004c4e1c` is this word in the old address base.) | confirmed |
| 1.2 | `0x26f620` clears `cfg[0xd7]` bit 0, mutes audio (`0x28cc75(0)`), sets the LED (`0x253607`), runs the panel-off sequence (`0x289488`), and requests PM mode 2 (`0x248d95(2)` writes `0x4ca730`). The next main-loop pass enters PM (0). So D6 = 4 is a real power-off, the same as the power key. | inferred (decompile), call order confirmed at `0x26b6d3/0x26b6d7` |
| 1.3 | Only in mode 2 the AP clears bit 4 of registers `0x11ad` and `0x12ad` before the hand-over; PM51 then runs its mode-2 branch (`PM:0x58a9`, `PM:0x844a(0)`). One of these drops DP HPD. Not resolved further. | inferred |
| 1.4 | PM51 wake configuration, bits of XDATA `0x5910/0x5911`, dispatched in `PM:0x58a9`. **Power-off** (`PM:0x9891` = `0x5c8f` + `0x5cd4`): only bit 3 (keys) and bit 4 (DDC/CI wake) stay set. **Standby** (`PM:0xa439`): bits 3 and 4 plus `0x5911` bits 0 and 1 (signal / DP activity). | confirmed (disassembly) |
| 1.5 | Bit 4 enables the hardware DDC/CI engines (`0xB7` to `0x3e0a/0c/0d/52/a2`, `PM:0x7379`), the same registers the AP uses for the HDMI DDC engines. The DP AUX path is not part of it. | confirmed for the writes, inferred for the meaning |
| 1.6 | PM51 turns a received power-mode command into a wake status (`PM:0x5e6e..0x5e8c`): value 5 -> status 6, value 4 -> status 5, anything else (so **D6 = 1**) -> status 7. `PM:0x9a16`: **status 7 wakes in both modes**; status 6 in standby converts standby into power-off; status 5 does nothing. | confirmed (disassembly) |
| 1.7 | AP boot (`0x26a9f3`, compares at `0x26aae9..`): wake status 7 or `0x0c` sets `cfg[0xd7]` bit 0 (power on) and saves it; `0x0f` is a key wake (key code in `0x4f82d8`); `0x0e` is a third variant; anything else is a signal wake that adopts the wake port only when source detection is auto. Status 0 with `cfg[0xd7]` bit 0 clear goes straight back to power-off (AC restored while off). | compares confirmed, effects inferred |
| 1.8 | PM51 also contains its own small DDC/CI responder (`PM:0x3de3`, capability string in the PM image) that answers Get VCP with canned values. So the monitor does answer DDC on the I2C DDC pins while asleep, but not with AP state. | inferred (decompile) |

### What this means

- **From the HDMI host (Mac), stock firmware:** Set `0xD6 = 1` on the HDMI DDC pins should wake the monitor from
  both standby and power-off (1.4, 1.6, 1.7). *Inferred*; this is the "DDC from the Mac while in standby" test
  already listed in the roadmap, and the code says it should pass. Unknown: whether HDMI HPD stays up in power-off so
  that macOS still offers the I2C channel.
- **From the DP host (PC):** impossible in power-off with any AP patch: HPD is down, the AP is not running, and the
  hardware DDC wake does not cover AUX. In **standby** (mode 1) DP activity is a wake source (1.4), so any AUX
  transaction probably wakes it (*inferred*; see section 2 for why this matters).
- A "PM wake on DP DDC" would need a patch of the 8051 program (keep HPD and the DP wake bits in the power-off
  configuration at `PM:0x9891`). The bytes are inside the flashable range, but there is no assembler, guard or test
  infrastructure for 8051 code and 1.3 is unresolved. **Not recommended now.**

### Patch design: soft standby (AP only)

Goal: D6 = 4 makes the monitor dark but leaves the AEON, DP HPD/link and DDC/CI running, so D6 = 1 from either host
turns it back on. All work happens in `sethook` and `poll` (cave code), using stock routines in the order the stock
power-off uses them.

| Command | New behaviour |
|---|---|
| Set D6 = 4 | soft standby: flag `EV+0x239 = 1`; `jal 0x28cc75` with r3 = 0 (mute); `jal 0x253607` (LED to the standby look); `jal 0x289488` (stock panel-off sequence, self-guarded by the panel flag `0x4ca78a`). Do **not** call the stock Set handler. Log event `0x14` |
| Set D6 = 1 | if the flag is set: clear it; `jal 0x289228` (stock panel-on sequence); `jal 0x28cc75` with r3 = 1; `jal 0x2535b9` (LED on). Log event `0x14`. If the flag is clear: nothing |
| Set D6 = 5 | real power-off: store 4 in the value byte `0x4c1b1e` and tail-call the stock handler `0x270b45` (lowest power, not wakeable from DP) |
| poll, flag set | if `0x4ca78a != 0` (stock code turned the panel on again, e.g. `0x25357f` when it shows a message): repeat the mute + panel-off calls, at most once per second (compare `EV+0x1c`) |
| Get D6 | 1 when on, 4 in soft standby (section 3.5) |

Leaving soft standby without a command: the power key performs a normal power-off (stock; next press boots with the
panel on), and "no signal" still leads to the real PM standby. Both clear the flag because the AP reboots. A direct
key wake (raw key read `0x28abdc`, `0x10` = power key, no side effects seen) can be added in `poll` later.

Risks:
- Panel sequencing. Only the stock sequences (`0x289488`, `0x289228`, tables at `0x4320cc` / `0x4320b8`) are used,
  never raw GPIO writes. `0x289228` waits in a loop for the ISR-driven counter `0x4ca796`: call it only from main-loop
  context (Set handler and poll both are).
- Stock code may fight the flag (OSD timeouts, mode changes). The poll re-assert covers it; flicker is possible when
  the PC changes mode while the monitor is dark.
- Power: the scaler stays on. Expect several watts instead of < 0.5 W. Tandem should prefer OS display sleep (real
  standby) for long idles and use soft standby when it must be able to wake by command.
- Windows keeps the display in the desktop while it is dark (windows can sit on it).
- The functions above are *inferred* from decompiles (jump-table sequences decompile badly). Before writing the patch:
  disassemble `0x289488`, `0x289228`, `0x28cc75`, `0x253607`, `0x2535b9` fully and confirm argument use and that
  none touches `cfg[0xd7]`.

## 2. DPMS hang (R16)

### What the code says

- **confirmed** The patch cannot run during the hang window proper: after `0x21387e` the AEON is in a masked,
  endless loop; in PM mode it is off; a wake is a full boot.
- **confirmed** The patched image is byte-identical to the stock dump in `flash:0..0x11000` (boot stages),
  `flash:0x11080..0x31080` (PM51 program, both config areas) and above `0x2c0000`. It differs only in 9 descriptor
  bytes at `flash:0x11008..0x11017`, 3 prefix bytes and the AP stream.
- **confirmed** The moved heap base is referenced once (the word at `0x4c1390`); the only `movhi/ori` pair building
  `0x4fe6b0` is the BSS bound at `0x2001a3/0x2001a7`. No other code assumes the old end of BSS.
- **confirmed** No patch routine has an unbounded loop (poll: fixed watches and an 8-byte scan; Get/Set handlers are
  straight-line). The timer hook only touches the 2 KB block.
- **confirmed** Power-off by D6 = 4 and wake by the power key worked on the patched unit today. That exercises the
  same hand-over (`0x248f20` -> `0x21387e`), PM51, and the full reboot of the patched AP. Only the mode (2 instead
  of 1) and the wake source differ.
- **confirmed** (from the test log of the failing run, not from firmware): the `desk` example kept scanning DDC over
  DP the whole time the displays were off. For about 50 s every scan was slow (2-5 s each; the log does not say
  which requests were answered), then the monitor was reported off for good. The script slept only 25 s before
  waking the displays.
- **confirmed** The symptom set (dark, LED off, keys dead, DDC dead, EDID still readable) is exactly what an AEON
  stuck with interrupts masked and PM51 not in charge would look like: keys and LED are serviced by whichever CPU is
  in charge, EDID comes from the hardware DDC RAM.

### Most likely root cause

*Inferred, medium confidence:* **stock behaviour, triggered by DDC traffic during the sleep/wake transitions, not by
patch code.** In standby PM51 treats DP activity as a wake source (1.4), so every poll from the PC wakes the
monitor; the AP boots (about 3 s, with the DP re-train noted in `overview.md`), finds no video, and goes back to
standby. With a client polling once per second and Windows waking the link 25 s later, the unit went through
several hand-overs and boots in a row with AUX traffic arriving at arbitrary points. Two places can then deadlock,
both stock:
1. the hand-over: the AP is already spinning at `0x2138d2` while PM51 is not (or no longer) waiting for a request
   (`PM:0x4a45` state 3 only loads the request when `0x10181e` reads 1; `PM:0x8c1d` overwrites that register with 0
   then 2 when it reports a wake);
2. the early boot after a wake, before the AP main loop services keys, LED and DDC.

What the patch contributes is indirect: it is the reason a client polls this monitor at all, and Get `0xEA..0xEF`
answers make the polling succeed until the last moment. Each such cycle also increments the boot counter and saves
`cfg[0xd7]` (EEPROM writes).

Less likely, not excluded by static analysis: a stock fault of this unit on plain DP display sleep with no DDC
traffic (the HIL "Standby and wake" item was never run, on stock or patched).

### Fix

1. **Client (now, no firmware):** `monitor-ddc`/Tandem must stop all DDC traffic to a monitor when the host turns
   its displays off (Windows `GUID_CONSOLE_DISPLAY_STATE`, macOS display sleep notifications), when the monitor's
   signal event says "lost", and for a settle time (propose 10 s) after it reappears. Never probe a sleeping monitor
   unless the intent is to wake it.
2. **Firmware (protocol 3):** the "standby imminent" event (section 3.1) lets clients stop before the hand-over.
   Nothing in the patch needs to change for the hang itself; PM51 is not touched.
3. If test B below hangs without any DDC client: compare with stock (`restore-stock`), then decide.

### Safe test plan (hardware, needs the user; a hang is recovered by a power-cable cycle, flash is not at risk)

| Test | Setup | Expect if the hypothesis holds |
|---|---|---|
| A | patched, **no DDC client running** (no desk, no monitor-events, no Tandem), displays off for 120 s, wake by mouse; 5 times | clean standby (note the LED) and clean wake every time |
| B | same with `desk` scanning | wake/sleep cycling visible as the LED and backlight coming up every few seconds; may hang |
| C | during standby from A, one single Get from the PC | the monitor boots, shows "no signal", sleeps again |
| D | if a hang occurs: from the Mac on HDMI send Get `0x10` then Set D6 = 1 | PM51 alive (canned reply, wake) means the AEON side hung; silence means PM51 is not in charge |
| E | only if A hangs: repeat A on stock 1006.0 | tells stock vs patch for good |

Record for each: LED state, seconds from "displays off" to dark, whether Windows keeps listing the monitor.

## 3. Events and state for Tandem

### 3.1 Power state with cause

- Wake cause is already in RAM after every boot: u16 at `0x4f82d4` (0 cold/AC, 7 or `0x0c` DDC power-on, `0x0f`
  key, other values signal/DP activity), port at `0x4f82d6`, key at `0x4f82d8` (compares **confirmed**, meanings
  *inferred*). Readable today with protocol 2 (Get `0xF2`).
- Going down cannot be reported after the fact (the AP dies one main-loop call after `poll`). What can be reported
  early: bit 1 of `0x4c1bfc` is set by the no-signal handlers (`0x2699d9`, `0x2741fe`) before the countdown
  (`0x4ca7aa/0x4ca7ab`, 5 ticks in `0x26afdb`) that ends in the standby request (`0x27cfe9`, `0x27cf1d`). *Inferred.*
- Proposed event `0x14` power-state: `new` = 1 on, 2 standby imminent, 4 soft standby, 5 power-off requested;
  `old` = cause: 0 cold boot, 1 DDC, 2 key, 3 signal/DP activity, 4 no signal. Logged at the first poll after boot
  (from the wake status), on soft standby on/off, on the rise of `0x4c1bfc` bit 1, and when `0x4ca730` becomes 2
  (best effort: rarely readable).

### 3.2 Signal on the inactive input

- **confirmed** `0x214323(port id)` dispatches on the port type through the table at `0x2fff3c`; `0x24a72e(port)`
  turns it into a boolean and `0x27cede()` returns a mask of ports 0..2 (bit 0 DP, bit 1 HDMI) with a cable/source
  detected. Stock code calls it for ports that are not on screen (it feeds the PM request block).
- *Inferred* (decompile): the leaves are plain GPIO reads with no state: HDMI at RIU offsets `0x904`/`0x90c` (bit 1
  with a polarity from `0x4c1a10`), DP at `0x95c`; a second DP read (`0x216ac3`, offsets `0x944/0x94c/0x954`) is the
  "source still attached" test used by `0x26adb1`.
- This is cable / source-power detect (HDMI +5 V, DP cable detect), **not** TMDS or link clock. A sleeping Mac that
  keeps +5 V up reads as present. No clock-detect read for the inactive port was found; the port structs
  (`0x3c3440 + n*0x8c`, `+0x1c`, `+0x22`) may or may not be updated for a port that is not displayed (unknown).
- Proposed event `0x15` signal-on-input: `old` = previous mask, `new` = mask from `0x27cede`, polled every 64th
  pass. The mask also goes into the capability/live reply (section 4).

### 3.3 Switch to an input without signal

*Inferred* from `0x2699d9`, `0x248f20`, `0x26a9f3`:
- Source detection **auto** (`0x20414f == 0`): the stock scan moves back to a port with signal (handler case 2
  rewrites `cfg[0xe5+n]`); our log shows `input-port` and then `switch-failed`.
- Source detection **manual**: the monitor stays on the dead input, shows the no-signal message, and enters standby.
  PM51 then watches only the displayed port, and at wake the AP ignores the wake port in manual mode. From the PC the
  monitor is then unreachable until the other source wakes or someone presses a key. This combination is the
  dangerous one for Tandem.
- Proposed guard in `sethook` for Set `0x60`: map the value to the target port, `jal 0x27cede`; if the target's bit
  is clear, log `switch-failed` at once and do not call the stock handler. Optional auto-revert when the 8 s verdict
  fails: store the previous selection in `0x4ccd83` and `jal 0x26e142` (the same two steps the stock Set `0x60`
  uses, **confirmed** in the decompile of `0x270b45`). The no-signal timers are loaded with 3, 60 or 300 units
  (`0x28b976`, ids `0x0e` and `0x17`); the unit is not known, so whether standby can come before 8 s must be measured.

### 3.4 Settings

| Offset | Meaning | Evidence | Confidence |
|---|---|---|---|
| `0x14f` | Source detection: 0 auto, non-zero manual. Menu item `0x42` (`0x27a421` / `0x27ac9c` adjust it with item id `0x42`) | read by the standby request builder, the boot wake handler and the no-signal handlers | inferred |
| `0x19f` | Auto power-off / off timer enable (1 = on): `0x2740c7` powers off when timer `0x0d` expires and this byte is 1 | also written by stock Set `0xE7` | inferred |
| `0x0bb` | Written together with `0x19f` by stock Set `0xE7` value `0x0000` / `0x0001` (high byte 0), both saved | decompile of `0x270b45` | inferred |
| `0x131` | Power LED mode (1 swaps the LED polarity in `0x253607` / `0x2535b9`) | decompile | inferred |
| `0x10a` | Volume (index into the table at `0x433870` in `0x28cc75`) | decompile | inferred |

Forcing manual over DDC needs no new firmware: Set `0xF0/0xF1` to `0x0020/0x414f`, Set `0xF4 = 1`, then Set
`0xF6 = 0x42` to run the stock apply-and-save for that item. *Inferred* until `map-setting` shows the event at
offset `0x14f` and item `0x42` is confirmed. Stock Set `0xE7 = 0` should disable auto power-off the same way.
Given 3.3, Tandem should run with source detection **auto** unless the switch guard above is in place.

### 3.5 Get 0xD6

- **confirmed** (bytes): the Get jump-table entry for `0xD6` (`0x377768`) is the address of the common reply tail
  `0x26fcd3` itself. The code is "supported" but no case block fills MH/ML/CH/CL, so the reply repeats whatever the
  previous request left there. That is the stale reply seen on hardware.
- Fix: point `0x377768` at a new `get_d6` in the cave: MH:ML = `0x0005`, CH = 0, CL = 4 if the soft-standby flag is
  set, else 1; `j 0x26fcd3`. (While the AP answers, the monitor is on by definition; asleep, PM51 answers.)

## 4. Protocol 3 patch plan (v3.2)

Free codes in the stock Get table (**confirmed**, entries equal to the unsupported block `0x26fd11`): `E3 E4 E7 E8`,
`EA..F2` (ours), `F4 F6`, `F8..FD`. Proposal: capability word on **`0xE8`** (must also be free on the G5).

Get `0xE8`: MH = cable mask (3.2), ML = flags now (bit 0 soft standby, bit 1 source detection manual),
CH:CL = capability bits: 0 real-input, 1 switch-verdict, 2 events, 3 power-wake (soft standby), 4 inactive-signal
(cable detect), 5 source-detect, 6 memory-access, 7 get-d6-truthful, 8 switch-guard.

| # | Site | Change | Guard in `versions/1006.0.toml` |
|---|---|---|---|
| 1 | `0x377768` (4 bytes) | Get table `0xD6` -> `get_d6` | new `get_table_d6` (stock value = reply tail) |
| 2 | `0x3777b0` (4 bytes) | Get table `0xE8` -> `get_e8` | new `get_table_e8` (stock = unsupported) |
| 3 | cave `get_ea` | ML = 3 | existing `code_cave` |
| 4 | cave `sethook` | D6 = 4 / 1 / 5 as in section 1; `0x60` switch guard (3.3) | existing `set_vcp_dispatch` |
| 5 | cave `poll` | boot cause event, `0x4c1bfc` bit 1 watch, soft-standby re-assert, cable mask every 64th pass (`0x15`), optional auto-revert | existing `main_loop_ddc` |
| 6 | no overwrite | stock callees used by new code | new `[symbols]`: `panel_off 0x289488`, `panel_on 0x289228`, `audio_mute 0x28cc75`, `led_standby 0x253607`, `led_on 0x2535b9`, `cable_mask 0x27cede`, `switch_apply 0x26e142`, `sel_request 0x4ccd83`, `pm_request 0x4ca730`, `pm_flags 0x4c1bfc`, `wake_status 0x4f82d4`, `panel_flag 0x4ca78a`; plus one hash guard per callee prologue (first 16 bytes) so a port to another version cannot call into the wrong place |

Not hooked on purpose: `0x26b6d7` (the PM entry call). Delaying the hand-over would make "going to standby" events
readable, but it changes the timing of the path involved in R16.

Space:
- Cave: 577 bytes free (2016 - 1439). Estimate: `get_d6` 40, `get_e8` 60, D6 logic 130, poll additions 190, switch
  guard 70, auto-revert 60 = about 550. It fits only without slack. Either drop auto-revert from v3.2 or prove a
  second cave. Zero runs inside `.text` that are candidates (**confirmed** zero, references **not** checked):
  `0x38cc9b` (9061 bytes), `0x386a26` (2268), `0x33c40b` (903). They may be zero-initialised constants; run
  `RefsInRanges` and a pointer scan before use, and add a zero guard.
- RAM: block uses `+0x000..0x23f`, `+0x400..0x63f`. New bytes: `+0x239` soft-standby flag, `+0x23a` cable mask
  snapshot, `+0x23b` `pm_flags` bit-1 snapshot, `+0x23c` u32 last re-assert time. No growth of the block.

Also required by the project rules: golden listing, FakeMonitor tests (soft standby on/off, Get D6, capability word,
events `0x14`/`0x15`, switch guard), `docs/protocol/vcp-interface.md` + CHANGELOG, an ADR for protocol 3.

## 5. Next steps (ordered)

1. **Client now:** stop DDC traffic while the host's displays are off and for 10 s after a monitor reappears.
2. **Hardware, no flash:** tests A-D of section 2. Confirms or rejects the R16 cause.
3. **Hardware, no flash:** from the Mac over HDMI: Get in standby and in power-off, then Set D6 = 1 in both.
   Confirms 1.4-1.8 and whether HDMI HPD survives power-off. From the PC: one Get during standby (test C) confirms
   the DP-activity wake.
4. **Hardware, no flash:** after wakes by key, by signal, by D6 = 1 and after a cold start, read `0x4f82d4..d9` with
   Get `0xF2`. Confirms the wake-cause table of 3.1.
5. **Hardware, no flash:** `map-setting` for "Source detection" and the off timer / eco power-off; then the
   `0xF4` + `0xF6 = 0x42` sequence. Confirms 3.4.
6. **Hardware, no flash:** with DP on screen, read the HDMI port struct (`0x3c34cc + 0x1c`, `+0x22`) with the Mac
   awake, asleep and unplugged. Tells whether a real signal flag exists for the inactive port (3.2).
7. **Static:** full disassembly of the five callees of the soft standby, `0x27cede` leaves, `0x26e142`; prove a
   second cave; check `0xE8` in the G5 Get table.
8. **Patch v3.2** in two flashes: first items 1-3 plus events and the cable mask (read-only behaviour), then soft
   standby and the switch guard. `hil-check` with the 30-minute standby/wake item after each.
9. **Later, only if needed:** PM51 work (resolve 1.3, DP wake in power-off). Needs an 8051 assembler path, guards
   for `flash:0x11080..`, and a tested SPI recovery for this monitor first.

## Open questions

- Which write drops DP HPD in power-off (AP registers `0x11ad/0x12ad` bit 4, or the PM51 mode-2 branch)?
- Does HDMI HPD stay asserted in power-off, i.e. can macOS still reach the DDC pins?
- Unit of the no-signal timers (ids `0x0e`, `0x17`), i.e. seconds from "no signal" to the standby hand-over.
- Meaning of wake status `0x0c` and `0x0e`, and of AP register `0x10fc` (if its three bytes read non-zero the AP
  skips the PM51 start sequence `0x2136a4` and only spins).
- Whether the hang needs DDC traffic at all (test A).

## How this was produced

Decompile search in `data/ghidra2/inst.c`; disassembly with `Dis.java` against `data/ghidra-ram`; raw checks of
`data/vendor/ram-installed.bin`, `data/dumps/LC34G55T-full-1.bin` and `out/mfw-v3.1.bin` with Python. The 8051 program
was cut from the dump and analysed in a throw-away Ghidra project outside the repository (8051 language, functions
seeded from LCALL targets); it is not kept in `data/`. To repeat: extract `flash:0x11080..0x1b930`, import at base 0.

## 6. v3.2 as built (2026-11-23, not flashed)

Source `firmware/targets/lc34g55t/patches/lc34-v3.2.s` (v3.1 source `lc34-full.s` untouched and still rebuilds
byte-identically), golden listing `listings/1006.0/v3.2.lst`. One image carries everything; there is no separate
stage A image (the code fits, with 11 bytes of the cave left, so a third feature needs a second cave).

Static checks done before writing the calls (**confirmed** in disassembly unless marked):
- `0x289488` panel-off: no arguments, returns at once when the panel flag `0x4ca78a` is 0, clears the flag, calls
  the mute itself (`0x28cc75` with 0), walks the sequence table at `0x4320cc`, clears bit 3 of `0x4c1bfc`. It does
  not touch `cfg[0xd7]`.
- `0x289228` panel-on: no arguments; when the flag is 0 it sets it, waits for the u16 at `0x4ca796` to reach 0
  (decremented in the 1 ms timer ISR, *inferred* from the decompile of `0x24d72d`), calls `0x274dda` and walks the
  table at `0x4320b8` with stock delays (up to ~0.6 s). `0x274dda` increments a counter in settings `0x0c1..0x0c6`
  and saves it: **every panel-on costs one EEPROM write** (stock behaviour; *inferred* from the decompile).
- `0x28cc75(r3)`: 0 mutes, non-zero restores the volume from setting `0x10a`. `0x253607` / `0x2535b9`: two GPIO
  writes each (`0x440/0x441` bit 4), polarity from setting `0x131`.
- `0x27cede`: loops ports 0..2 over `0x24a72e`, saves and restores r10..r12, returns the mask in r3. Bit set means
  the port's detect routine returned non-zero. That this means "cable present" (and not the inverse) is *inferred*
  from the GPIO leaves and from the no-signal handler, which shows the cable message when the bit is clear.
- `0x28abdc` raw key read: called from one place only, `0x28aca8` inside the debounced reader `0x28ac95`.
- Second cave: not needed, not proven. `0x26e142` is not called (auto-revert was dropped for space).

Differences from the plan in section 4 (the protocol document is unchanged by them):
- **Key wake needs one more hook.** The call at `0x28aca8` now goes to `keyhook`, which calls the stock raw key
  read and, only in soft standby, turns the first key press into a wake request and hides keys from the stock code
  until release. Without it the power key would have performed a real power-off. Any key wakes, not only power.
  The wake is logged as `0x14` old 2, new 1.
- **Standby imminent** comes from the countdown flag `0x4ca7aa` or the request word `0x4ca730` becoming 1, not from
  bit 1 of `0x4c1bfc` (that bit is set and consumed inside one main-loop pass, so the poll would never see it).
  When the source is not attached there is no countdown and the event is logged one call before the hand-over, so
  it is rarely readable. *Inferred* lead time; measure it.
- `0x14` with new 5 and cause 2 is logged for every power-off request that did not come from Set D6 = 5 (key, off
  timer, AC restored while off). It is also rarely readable.
- The first `0x15` after boot has old = `0xEE`, like the other watches. Get `0xE8` MH is read fresh on each Get.
- The switch guard logs `0x10` first and then `0x12` (old = target, new = current port) and never calls the stock
  handler. The capability word is `0x01FF`.
- Re-assert interval in soft standby: 2 s.

Sites and guards added to `versions/1006.0.toml`: `key_read_call` (`0x28aca8`), `get_table_d6` (`0x377768`),
`get_table_e8` (`0x3777b0`), and seven `callee_*` guards (first 16 bytes of each stock routine called). `mfw`'s
version loader now skips version maps of other platforms (the Novatek G5 map made `mfw identify` and three tests
fail).

Space: cave `0x399820..0x399ff5` used, 2005 of 2016 bytes. RAM block: `+0x239..0x23f` newly used, no growth.

Image (local, ignored): `out/lc34-v3.2.bin`, built from `data/dumps/LC34G55T-full-1.bin` with zopfli, `mfw verify`
OK, 2127 bytes applied, sha256 `bb41db8a48a3a4c870797121b054e2ba6261770d959defb7bdbf522f07960701`, flash range
`-Start 11000 -End 2c0000` (305 sectors differ from stock, 298 from the installed v3.1).

## 7. HIL runbook for v3.2

Needs the user at the monitor. Nothing here was run. Keep the power cable reachable. Recovery at any point:
a hang (dark, no LED, keys dead) is cleared by unplugging power for 30 s; a bad flash or bad behaviour that
survives a power cycle is fixed with the `restore-stock` skill (or by flashing `out/mfw-v3.1.bin` again). The boot
stages and the standby program are not written, so the ISP route stays available.

### Before flashing (current v3.1)

1. Quit every DDC client (Tandem, `desk`, `monitor-events`). Turn the PC's displays off for 120 s, wake with the
   mouse; five times (test A of section 2). Note the LED in standby. **If this hangs, stop:** the hang is not
   caused by polling, and v3.2 must wait for the stock comparison (test E).
2. Optional, same firmware: tests C and D of section 2, and steps 3-6 of section 5.

### Flash

3. `flash-monitor` skill with `out/lc34-v3.2.bin`, backup `data/dumps/LC34G55T-full-1.bin`,
   `-Start 11000 -End 2c0000`. Compare the SHA-256 after copying to Windows.

### Stage A: read-only behaviour (do all of it before any Set 0xD6)

| # | Step | Expect |
|---|---|---|
| A1 | Picture comes up; press a menu key, open and close the OSD, change brightness with the keys | all normal. This is the first test of the key hook: **if keys are dead or erratic, go back to v3.1** |
| A2 | `monitor-events status`, Get `0xEA` | ML = 3 |
| A3 | `history` | `boot`, then `power-state` old 0 new 1 (cold start after flashing may show cause 0), then the initial watches, and within a second `cable-mask` old `0xEE` |
| A4 | Get `0xE8` with both computers connected and awake | MH = 3, ML = 0 (or 2 if source detection is manual), CH:CL = `0x01FF` |
| A5 | Unplug the HDMI cable at the monitor, wait 2 s, Get `0xE8`, read history; plug it back | MH = 1 and a `cable-mask` 3 -> 1 event; back to 3 after plugging. **If the bits are inverted (MH = 2 while only DP is connected), stop using the switch guard and report it: one instruction flips it** |
| A6 | Same with the Mac asleep but connected | records whether a sleeping Mac still reads as present |
| A7 | Get `0xD6` eight times, interleaved with Get `0x10` | always MH:ML = 5, CH:CL = 1 |
| A8 | Switch DP -> HDMI -> DP with both sources awake | `switch-done` both ways, as on v3.1 |
| A9 | HDMI cable unplugged, Set `0x60 = 6` | no switch, picture stays; history shows `ddc-switch-request` then `switch-failed` old 1 new 0 at once |
| A10 | Power key off, power key on | normal; after boot `power-state` cause 2 (key) |
| A11 | No DDC client running: displays off 120 s, wake by mouse; three times | normal standby and wake; after each wake `power-state` cause 3 |
| A12 | One client polling at 1 Hz: let the PC's displays turn off | look for `power-state` new 2 before the monitor leaves; note how many seconds of warning there were |

### Stage B: soft standby (only if stage A is clean)

| # | Step | Expect |
|---|---|---|
| B1 | Set `0xD6 = 4` from the PC | panel dark within about a second, LED in its standby look, audio muted. Windows keeps listing the monitor; Get `0xD6` = 4; Get `0xE8` ML bit 0 set; events `0x13` (new 4) and `0x14` old 1 new 4 |
| B2 | Wait 60 s, move windows, change nothing else | stays dark; no flashing of the backlight. **If the panel flickers on and off every 2 s, wake it (B3) and report: stock code is fighting the flag** |
| B3 | Set `0xD6 = 1` | picture back in about a second, LED on, audio back; Get `0xD6` = 1; `0x14` old 1 new 1 |
| B4 | Set `0xD6 = 4`, then press the power key once | picture back (not a power-off); `0x14` old 2 new 1; the key does nothing else. Press power again: normal power-off |
| B5 | Set `0xD6 = 4`, then press a menu key | wakes; the OSD does not open from that press |
| B6 | Set `0xD6 = 4` from the PC, Set `0xD6 = 1` from the Mac over HDMI (and the reverse) | either host can wake it |
| B7 | Set `0xD6 = 4`, then let the PC turn its displays off (no DDC client polling) for 120 s, wake by mouse | real standby, then a normal wake with the picture on and Get `0xD6` = 1 |
| B8 | Set `0xD6 = 4`, switch input with Set `0x60` | switch works while dark (verdict events), still dark; wake shows the new input |
| B9 | Set `0xD6 = 5` | real power-off as with the key; the PC loses the monitor; power key brings it back, `0x14` cause 2 |
| B10 | Soft standby for 30 minutes, then wake | wakes; `0xEF` clock kept running; no gaps in the event sequence |
| B11 | `hil-check` skill, full checklist including the 30-minute standby/wake item | all pass |

Measure with a watt meter if one is at hand: on, soft standby, real standby.

### Still inferred after the build, settled by the steps above

- Cable-mask polarity and what a sleeping Mac reads as (A5, A6).
- That the key hook is transparent outside soft standby (A1, A10) and that one raw read is enough to detect a key
  without false wakes (B2, B10).
- That the stock panel sequences are safe to call from the Set handler and the poll, and that nothing in the stock
  code keeps turning the panel back on (B1-B3, B10).
- Lead time of "standby imminent" (A12) and the wake-cause values (A3, A10, A11).
- That source detection is settings offset `0x14f` (A4 ML bit 1 against the OSD setting).
