# Tandem HIL session: both monitors, protocol 3

Order for the next session with the user present (each flash needs the user's go-ahead in that session). Detailed
steps, expected results and recovery are in the per-monitor runbooks; this page only fixes the order and the stop
rules. Tool for every check: `crates/monitor-ddc/examples/desk.rs` built for Windows (`cargo build --release
--example desk --target x86_64-pc-windows-gnu`), commands `status`, `watch`, `switch`, `power-off`.

## 0. Before anything (no flash)

1. Windows display sleep **off** on the PC until step 1 passes (R16).
2. Test A (`docs/targets/lc34g55t/tandem-re.md` §2/§7): PC turns its displays off with **no DDC client running**,
   wait 2 min, wake. Hang again → stop: R16 is not the polling, investigate before any flash.
3. Read the G5 OSD version (Support → Information): decides whether stock 1008.3 goes first by USB.
4. Mac access for the HDMI tests (`ssh mac-runner` or the user runs the commands).

## 1. 34" v3.2 (ISP flash, `flash-monitor` skill, verified backup of v3.1)

Read-only checks first (0xEA = protocol 3, 0xE8, Get D6 = 1, cable mask with the Mac's cable in/out, buttons and OSD
work normally), then switch guard, then soft standby (D6 = 4 → dark, still listed and answering; D6 = 1 wakes; a key
wakes), then D6 = 5 (real off). Then the 30-minute standby/wake HIL item with `desk watch` running (it probes a
standby monitor only every 10 s). Stop rule: any key, OSD or picture misbehaviour → `restore-stock` to v3.1.

## 2. G5 p3a → p3b → p3c (USB updater only; SPI clip as last resort)

p3a: 0xE8, Get D6, D6 = 4/5 powers off (key wakes). p3b: soft standby with D6 = 1 wake from the PC over DP. Free-RAM
soak (OSD use, switches, reload, standby) before p3c. p3c: `desk status` must show the G5 as `standard`, switches
`Confirmed`, OSD changes as `InputChanged by_this_host: false`, switch guard with the Mac's cable out. Stop rule:
anything odd → unplug both video cables (the hooks only run on DDC traffic), power-cycle, re-flash stock by USB.

## 3. Tandem

Both monitors `standard` protocol 3 → Tandem moves to the `monitor-ddc` commit with `Desk` and protocol 3; repeat
the desk table of `tandem-firmware.md` §0.2 from the PC and from the Mac.
