# G5 (FALCON) — Tandem feature RE and patch plan (static analysis)

Static reverse engineering of the stock **M-C5500GGZA-1008.3** SPARC main app (the image extracted under
`data/vendor/g5/stock-1008.3/`, confirmed id string at file `0x273358`) to make the G5 give Tandem the same
features as the patched 34": power on/off by command, truthful input + switch verdict + events, inactive-input
signal, and a safe production image. Scope is **static only**; no monitor was touched. Confidence per ADR-0001:
**confirmed** = bytes/disassembly I read in this image; **inferred** = reasoned from them or from prior hardware
notes in `firmware-re.md`.

Address convention (same as `firmware-re.md`): SPARC code uses **nominal VA**, file = VA + `0x2E000` (code) /
VA + `0x2DD00` (data). At runtime code is relocated by **+0x320** (so a Set/Get hook composed against nominal VAs
works; the existing `*_hook.py` builders already apply this). All code addresses below are nominal.

Anchors re-confirmed in this image (match `firmware-re.md`): Get-VCP handler `SecLibCommon_DdcCmdGetVcp` `0x1882AC`,
Set-VCP `SecLibCommon_DddCmdSetVcp` `0x1869BC`, DDC/CI command dispatcher `sub_103DBC` `0x103DBC`, Get call-site
`0x103EBC`, Set call-site `0x104170`, dead code region `0x1E14EC` (hook body), BSS slot window `0xA803CFC0`
(hardware-proven writable, 1020.1+).

---

## Goal 1 — Power on/off by command

### Why stock 0xD6 does nothing (confirmed)

`DddCmdSetVcp` (`0x1869BC`) dispatches by an explicit compare chain, not a full table. The only VCP codes it
compares are **0xE5, 0xEC, 0x62, 0xB0, 0x04, 0x60, 0x02**, plus a vendor sub-chain (0xE7/0xE9/0xEB/0xEF, where
0xEB indexes a 0x31-entry sub-table). **0xD6 is never compared**, so it falls through to the default tail
(`mov 0,%i0` → returns "unsupported"). This is the byte-level reason Set 0xD6 = 1/4/5 has no effect and Get 0xD6
reads 0/0 (confirmed; matches the 2026-11-23 hardware result).

### The stock power path exists and is reachable (confirmed)

The firmware has a full soft-power state machine, just not wired to DDC:

| Function | VA | Role |
|---|---|---|
| `SecLibPower_SetPowerState` | `0x1ADACC` | arg: 0=On, 1=On(DC), 2=Off:DPMS, 3=PowerSaving, 5=Wakeup. Drives panel/backlight, LED (`0x18A830`/`SetLED`), EEPROM save, calls `SecHalBoard_SetPanelPower`. 18 callers. Confirmed by its debug strings `[Power] ON`, `[Power] OFF:DPMS`, `[Power] OFF:DC`. |
| power-state dispatcher | `0x1035D0` | **no direct callers** → invoked via the app attention/function-pointer table. Takes a requested state (`%i0`) + a cause (`%g1` = 0x20/0x30). Routes to `0x10345C` and notifies the 8051 (`0x16DBB8`). |
| power actuator | `0x10345C` | `0x10345C(0)`=On/wake (→`SetPowerState`), `0x10345C(2)`=Off/standby, `(3)`=saving, `(4)`. Calls `SetPowerState`, panel, OSD, and `0x16DBB8` (STBC/8051 notify). |
| STBC power notify | `0x16DBB8` | tells the 8051 the new power state (mailbox cmd 0x16/0x17 PowerSaving/PowerOff region). |

The event name table carries `SECAPP_APPEVT_DDCCI_PWR_ON/OFF/SAVING` and `SECAPP_APPATN_PWR_ON/OFF/WAKEUP` strings
(data `0x205C80`/`0x205030`/`0x2054E0`) — i.e. the firmware was designed with a **DDC-CI power event** class, but in
1008.3 nothing posts them (no code xref to those names). So the plumbing from "DDC power request" to the power
machine is present but disconnected.

### Patch design (power by D6)

Add a **Set-VCP 0xD6 interception** at the existing Set call-site redirect (`0x104170` → hook in the dead region,
exactly as the dev hooks already redirect it). In the hook:

- `D6 == 4 or 5` → `call 0x10345C` with `%o0 = 2` (Off:DPMS/standby). This is the same actuator the internal
  "off" attention uses; backlight/panel off, LED to standby, 8051 notified. (inferred: path confirmed, effect not
  yet observed on hardware.)
- `D6 == 1` → `call 0x10345C` with `%o0 = 0` (On), i.e. wake. (inferred.)
- Store the last requested D6 in a BSS slot so a Get 0xD6 can echo it (truthful D6), and post event id `0x14`
  power-state (see Goal 2).
- All other codes branch to the real `DddCmdSetVcp` (`0x1869BC`), unchanged.

### The wake-from-off problem (the hard part)

`0x10345C(0)` wakes the panel **only if the SPARC main loop and the DDC dispatcher are still running** when the
command arrives. The 2026-11-16 hardware note is decisive here: **in standby the DDC/CI reply buffer returns the
previous (stale) frame** — the SPARC DDC service is not polling. So:

- `D6 = 4` (enter standby) from the host is feasible: the command is processed while the SPARC is awake.
- `D6 = 1` (wake) from the host is **likely not feasible as a pure SPARC patch**: once in DPMS/off the SPARC isn't
  servicing DDC, so the hook never runs. (inferred, strong.)

Who stays alive in standby: the **8051 (STBC)** owns the mailbox/DDC buffer (bank 0 at `0x9F0A0100`, shared with
our DDC/CI frames) and the power/wake sources. Confirmed wake sources in the SPARC strings (read by the 8051 and
reported up): `IsWakeupByJogPowerKey`, `IsWakeupByJogLeftRightKey`, `IsWakeupByCableDisconnection`,
`IsWakeupByOtherSourceCableConnection` (`0x1241B8`..`0x1242E4`) and `[Power] Wake Up Evt - PowerKey/LRKey/CablePlug`
(`0x1777CC`). **There is no "wake by DDC address match" among them** (inferred from the enumerated wake conditions).

Two possible wake routes, both research-grade:

1. **Soft standby** (preferred, lower risk): make `D6 = 4` NOT call the full `SetPowerState(2)` but a reduced path
   that only turns the backlight/panel off (`SecHalBoard_SetPanelPower(OFF)`, referenced `0x195C94`) while keeping
   the SPARC main loop and DDC dispatcher running. Then `D6 = 1` is handled normally. Cost: the panel is dark but
   the scaler draws more power than real standby, and DPMS/no-signal would still take the real path. Needs a free
   RAM flag so the main loop skips its own standby transition while "soft off". (inferred; needs HW proof that the
   main loop keeps serving DDC with the panel forced off.)
2. **8051-side DDC wake**: patch the 8051 standby loop to watch for a DDC/CI write and raise a wake. The 8051
   runtime is understood (mailbox dispatcher, `CMD_SYS_POWERSAVING 0x16` / `POWEROFF 0x17` at `0x2949`/`0x297B`),
   but adding a DDC watcher there is a much larger change and ties into the flash-reset hazard
   (`firmware-re.md`). Not recommended for first scope.

**Risk:** calling `0x10345C`/`SetPowerState` from the DDC context (interrupt/dispatcher) may re-enter code that
assumes it runs from the app task; the internal callers run from the attention dispatcher, not the DDC handler.
Mitigation: post an attention/event instead of calling the actuator inline (set a BSS "power request" byte the main
loop polls), mirroring how the stock `DDCCI_PWR` event class was meant to work. (inferred.)

---

## Goal 2 — Real input + switch verdict + event ring

### Truthful input (confirmed, already works stock)

`DdcCmdGetVcp` code **0x60** (jump-table entry at base `0x184C0C`, nominal target `0x189634`) calls
`SecLibSource_GetCurrentSecSourceName` (`0x1B02C0`) and maps the source index through a table at data `0x3B0038`
(stride 6: index → {port, vcp-value}) to the reply. It reports the **shown** input, not a stored request — this is
why Get 0x60 was truthful on hardware. The mapped VCP value is also cached at BSS `0xA803B109`. No patch needed for
F1.

Set 0x60 (`0x186DA0`) stores the requested value and triggers the switch; the real switch is done by
`SecHalScaler_SetInputSource` (`0x1229F8`) via the Com/source module (`0x11E818`, `0x1B041C`). The "shown input"
truth variable is whatever `0x1B02C0` reads (a HAL/source-state byte), not the Set-0x60 request byte — good for a
verdict.

### Signal-present / picture-locked state (confirmed anchors)

The per-window sync state is maintained by `SecHalScaler_UpdateSyncState_CallBack` (`0x123620`, callers
`0x1761F0`/`0x176240`/`0x176254` in the sync handler/main loop). Its states are named in data:
`SEC_SYNC_NONE/WAITDATAREADY/MODE_SEARCH/SYNC_OOR/SYNC_NORMAL` (`0x242B98`). "Picture locked & present" =
`SYNC_NORMAL`. Per-source presence is also exposed by `SecHalScaler_CheckSourceHasSignal(<source>)` and
`SecHalScaler_IsCableConnectedBySourceName(<source>)` (referenced from the debug menu at `0x198A..`). These are the
building blocks for the switch verdict (switch-done = target source reaches `SYNC_NORMAL`; switch-failed = stays
`NONE` after a timeout) and for Goal 3's inactive-input signal. (anchors confirmed; exact HAL getter VAs to pin in
Phase D.)

### Event ring and hook points

- **Hook points (confirmed):** the DDC dispatcher `sub_103DBC` Get call-site `0x103EBC` and Set call-site
  `0x104170` are the proven interception points (the dev hooks already redirect both). The main loop that runs
  `UpdateSyncState_CallBack` and the power dispatcher is the place to **detect** state changes and push ring
  entries; the 0x103EBC/0x104170 redirects are where the host **reads** the ring (Get 0xEA..0xEF) and issues
  commands.
- **Get-VCP codes for the ring:** in the stock Get jump table (base `0x184C0C`), code **0xEA maps to the generic
  "unsupported" target `0x188300`** (returns 0), so 0xEA is free to repurpose by dispatcher interception. **But
  0xEB/0xEC/0xED/0xEE/0xEF have real stock handlers** (`0x188A88`/`0x1886BC`/`0x1889B8`/`0x1888E0`/`0x1884B0`) —
  unlike the 34". So protocol 3's `0xEA..0xEF` ring must be served by **intercepting at `0x103EBC`** (compare the
  code, serve the ring, else branch to real `DdcCmdGetVcp`), exactly as the dev `F2/F3` codes already do — not by
  editing jump-table entries. (confirmed.)
- **Event ids** like the 34": `0x14` power-state, `0x15` signal-on-input, reusing the existing 0xEA..0xEF frame
  shape.

### Verified-free RAM for the ring (the 1019.0 lesson)

1019.0 slots at `0xA8039A00` **overlapped a live 16-byte settings-record table at 0xA8039910..** (hardware-confirmed
corruption). The proven-safe window is **BSS `0xA803CFC0`** (top of the largest unreferenced gap
`0xA803C3E8..0xA803D000`); 1020.1..1021.x wrote/read it with no corruption. To *prove* a RAM region is free before
trusting it for the ring, take DDC snapshots (via a dev read code) of the candidate bytes across: (a) OSD setting
changes, (b) an input switch, (c) a settings reload/power-cycle, (d) entering/leaving standby — the region is free
only if it never changes under any of these. The static evidence for `0xA803C3E8..0xA803D000` is "no code reference
targets it" (my reference index finds none); combine with the snapshot proof in Phase D. (inferred + prior HW.)

---

## Goal 3 — Signal on the inactive input / no-signal switch

- Inactive-input signal is answerable **without a patch** at the firmware level via
  `SecHalScaler_CheckSourceHasSignal(<source>)` / `IsCableConnectedBySourceName(<source>)` (anchors above): a hook
  can read the inactive port's presence and surface it as event `0x15` or a capability field. (inferred; HAL getter
  VA to confirm.)
- **Auto source-switch** behaviour is real and is the risk R9: the firmware has
  `__AutoSource_SetSourceToNewConnectedSource` (`0x17649C`) and `[AUTOSRC]`/`SECAPP_OSD_AUTO_SRC_EVENT`
  (`0x17F108`), i.e. with source-detection "auto" the monitor **will hop to a newly-connected source by itself**.
  Whether it hops *back* when a switched-to input has no signal is governed by this module; statically it reacts to
  *cable connect* events, so an input with a plugged-but-sleeping source should NOT trigger auto-hop, but an
  unplugged cable will. (inferred — needs the unplug test from the Phase A matrix.)
- The source-detection setting itself is an OSD/settings item (map with the `map-setting` route via the menu engine)
  — forcing it to "manual" over DDC is the clean Tandem fix and avoids a firmware change for F8. (inferred.)

---

## Goal 4 — Boot-time DDC stall

Mechanism (inferred, consistent with all evidence): the DDC/CI responder is the **SPARC** dispatcher `sub_103DBC`,
run from the main app task. During boot the main loop is not yet serving DDC (long scaler/panel init), and the
shared mailbox/DDC buffer is owned by the 8051 (`0x9F0A0100`). So host `dxva2`/capabilities transactions either get
**I2C clock-stretched** by the scaler or are answered from a **stale buffer** until the SPARC starts polling —
matching the ~60 s capability block and the "stale previous frame" standby behaviour. The capabilities string is the
worst case because it is a long multi-segment read that must be assembled by the live handler.

Can a patch make it answer (or NAK fast) during boot? Partially, and it is **not first-scope**:

- A pure SPARC patch cannot help before the SPARC main loop runs; the hook lives in that same code.
- A minimal mitigation is to have the SPARC, very early in init, mark DDC "busy/again" so the host gets a fast
  defined reply instead of a 60 s stretch — but the earliest safe injection point in boot is not mapped, and the
  8051 holds the bus first. (inferred.)
- Practical answer for Tandem: keep the **client-side** mitigation already in ADR-0020 (never re-read capabilities
  of a known unit; read once without retries; 30 s backoff). Firmware boot-DDC work is optional and low priority.

---

## Goal 5 — Production image plan (protocol 3, no memory/call codes)

Same codes and event ids as the 34": `0xEA..0xEF` ring, a capability word, event ids including `0x14` power-state
and `0x15` signal-on-input. **No** memory-write / function-call / SPI codes in the shipped image (F9). Built with the
existing Python patch builders (`devtools_hook.py`/`final_hook.py` lineage, restamp + per-record sum16 + whole-file
sum16 + filename tag via `mfw.novatek`) and flashed **only** through the proven USB `.img` updater. Staged one
feature per image; SPI clip (CH341A, proven 2026-11-22) as recovery. **Never** the DDC flasher (2026-11-16 brick).

Patch sites (all confirmed addresses; sizes are hook-body estimates):

| # | Site (nominal VA / file) | Change | Size | Guard to add to `versions/1008.3.toml` |
|---|---|---|---|---|
| S1 | Get call-site `0x103EBC` / `0x131EBC` | redirect `call 0x1882AC` → ring/caps hook | 4 B | stock bytes = `call 0x1882AC`; record expected opcode |
| S2 | Set call-site `0x104170` / `0x104170+0x2E000` | redirect `call 0x1869BC` → command hook (D6, verdict trigger) | 4 B | stock bytes = `call 0x1869BC` |
| S3 | hook body in dead region `0x1E14EC` / `0x2125EC` | protocol-3 state machine: 0xEA..0xEF ring, D6→`0x10345C`, capability word, event push | ≤ `0x280` B | region is 0-caller dead code (verify no xref at build) |
| S4 | BSS ring/flags at `0xA803CFC0` | ring buffer, cursor, power-request flag, last-D6 | ~0x40 B | assert region unreferenced; snapshot-proof in HIL |
| S5 | main-loop tap (near `UpdateSyncState_CallBack` caller `0x1761F0` and power dispatcher `0x1035D0`) | detect input/signal/power change → push event id 0x14/0x15 | small | confirm caller bytes; one site per event source |
| S6 | version/id at file `0x273358`/`0x273364` | restamp `M-C5500GGZA-NNNN.N` + `[XXXX]` | — | `mfw.novatek.restamp` already handles it |

Guards follow the repo rule "every overwritten site needs a guard in the version TOML" with the **stock bytes'
hash**, not the bytes. No write below `0x11000`; all sites are in the SPARC code record (flash `0x108000+`).

Staging order (each a separate USB image, stock re-flashable between failures):
1. **Truthful input + capability word** (read-only additions: S1/S3/S4 ring skeleton + Get 0xEA ML=3 + cap word).
2. **Power off by D6=4** (S2/S3 → `0x10345C(2)`), plus event `0x14`. Highest-value, lowest-risk power step.
3. **Switch verdict + signal events** (S5, event 0x14/0x15 from the sync-state tap).
4. **Power on / wake** — only if the soft-standby approach (Goal 1) proves the main loop keeps serving DDC with
   the panel forced off; otherwise ship "wake by signal" and document D6=1 as unsupported.

---

## Risks

- **R-pow**: calling the power actuator from the DDC/dispatcher context may re-enter task-only code → prefer a
  polled "power request" BSS flag over an inline call. (inferred)
- **R-wake**: wake-by-DDC is probably impossible without soft-standby or an 8051 change; do not promise D6=1.
- **R-ram**: any ring RAM must pass the snapshot proof; 1019.0 already corrupted settings once.
- **R-brick**: USB updater + SPI clip only. No DDC flasher. A patch that also breaks boot/updater = SOIC-8 recovery.
- **R-auto**: auto-source may fight Tandem; prefer forcing source-detection=manual over DDC (setting map) to a
  firmware change.

---

## Next steps (ordered; HW test that confirms each inference)

1. **Confirm which image bank A runs now** (OSD version, or dev Get 0xF2 magic). Decides whether to re-flash stock
   1008.3 before Phase D. *(HW: read OSD / DDC.)*
2. **Power-off by D6 proof** — build an image that only intercepts Set 0xD6=4 → `0x10345C(2)` (polled-flag variant),
   flash by USB, test `D6=4` turns the panel/backlight off with the LED in standby and DDC still answering briefly.
   *(Confirms Goal 1 off-path and the actuator-from-DDC concern.)*
3. **Soft-standby experiment** — variant where D6=4 forces panel off but keeps the main loop/DDC alive; test whether
   Get 0x10/0x60 still answer fresh and D6=1 then wakes the panel. *(Confirms/kills the only host-side wake route.)*
4. **Free-RAM snapshot proof** of `0xA803C3E8..0xA803D000` across OSD change / switch / reload / standby before
   trusting it for the ring. *(Confirms Goal 2 RAM.)*
5. **Switch-verdict tap** — read `UpdateSyncState_CallBack` state and `CheckSourceHasSignal` over DDC (dev read)
   during a real switch and an unplugged-cable switch, to confirm SYNC_NORMAL = done and the no-signal/auto-hop
   behaviour (Goals 2/3). *(HW: switch with/without signal.)*
6. **Boot-DDC**: time capability/0x10 reads from cold boot to confirm the SPARC-not-serving hypothesis; decide if an
   early NAK patch is worth it (likely not). *(HW: cold-boot timing.)*
7. Only then assemble the staged protocol-3 images (Goal 5) with the version-TOML guards.
