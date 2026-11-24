//! The desk API against both fake monitors: state, input, changes, failures, power (no hardware).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::sync::Arc;
use std::time::Duration;

use monitor_ddc::fake::{
    BusOp, FakeBus, FakeClock, FakeMonitorConfig, Personality, SwitchBehavior, test_edid,
};
use monitor_ddc::{
    DdcError, Desk, DeskEvent, Input, InputTruth, MonitorHandle, MonitorId, MonitorState, Power,
    Presence, SwitchResult,
};

const TIMEOUT: Duration = Duration::from_secs(10);

/// The 34" as the PC sees it (DP EDID product) and the G5 over DP.
fn lc34_dp() -> FakeMonitorConfig {
    let mut c = FakeMonitorConfig::new(Personality::Standard);
    c.edid = test_edid("SAM", 0x711A, "LC34G55T", "FAKE0000001");
    c
}

fn desk_with(configs: Vec<FakeMonitorConfig>) -> (FakeBus, Vec<MonitorHandle>, Desk) {
    let bus = FakeBus::new(FakeClock::new());
    let handles = configs.into_iter().map(|c| bus.add(c)).collect();
    let desk = Desk::new(Arc::new(bus.clone()), Arc::new(bus.clock()));
    (bus, handles, desk)
}

fn by_name(desk: &Desk, name: &str) -> MonitorState {
    desk.states().into_iter().find(|s| s.name == name).unwrap()
}

fn id(desk: &Desk, name: &str) -> MonitorId {
    by_name(desk, name).id
}

/// Scans until `off_after` (5 s) has passed since the first miss.
fn scan_past_debounce(bus: &FakeBus, desk: &mut Desk) -> Vec<DeskEvent> {
    bus.clock().advance(Duration::from_secs(5));
    desk.scan().unwrap()
}

fn sets(bus: &FakeBus, h: MonitorHandle) -> Vec<(u8, u16)> {
    bus.ops_for(h)
        .into_iter()
        .filter_map(|op| match op {
            BusOp::Set { code, value, .. } => Some((code, value)),
            _ => None,
        })
        .collect()
}

#[test]
fn first_scan_reports_both_monitors_with_input_and_owner() {
    let mut g5 = FakeMonitorConfig::g5();
    g5.input = Input::Hdmi; // showing the Mac
    let (_bus, _h, mut desk) = desk_with(vec![lc34_dp(), g5]);
    let events = desk.scan().unwrap();
    assert_eq!(
        events
            .iter()
            .filter(|e| matches!(e, DeskEvent::Appeared { .. }))
            .count(),
        2
    );
    let big = by_name(&desk, "LC34G55T");
    assert_eq!(big.kind, Some("standard"));
    assert_eq!(big.presence, Presence::Present);
    assert!(!big.off);
    assert_eq!(big.status.unwrap().input, Some(Input::DisplayPort));
    assert_eq!(big.status.unwrap().power, Power::On);
    assert_eq!(big.status.unwrap().signal, Some(true));
    assert_eq!(big.host_input, Some(Input::DisplayPort));
    assert_eq!(big.shows_this_host(), Some(true));
    assert_eq!(big.capabilities.unwrap().input_truth, InputTruth::Firmware);

    let small = by_name(&desk, "Odyssey G5");
    assert_eq!(small.kind, Some("g5-falcon"));
    assert_eq!(small.status.unwrap().input, Some(Input::Hdmi));
    assert_eq!(small.status.unwrap().signal, None);
    assert_eq!(small.shows_this_host(), Some(false));
    assert_eq!(small.capabilities.unwrap().input_truth, InputTruth::Polled);
    // A quiet second scan reports nothing.
    assert!(desk.scan().unwrap().is_empty());
}

#[test]
fn own_switches_are_reported_as_this_hosts_on_both_monitors() {
    let (bus, _h, mut desk) = desk_with(vec![lc34_dp(), FakeMonitorConfig::g5()]);
    desk.scan().unwrap();
    for (name, proof) in [("LC34G55T", true), ("Odyssey G5", false)] {
        let id = id(&desk, name);
        let result = desk.switch(&id, Input::Hdmi, TIMEOUT).unwrap();
        assert!(result.succeeded(), "{name}: {result:?}");
        assert_eq!(matches!(result, SwitchResult::Confirmed { .. }), proof);
        bus.clock().advance(Duration::from_secs(2));
        let events = desk.scan().unwrap();
        assert_eq!(
            events,
            vec![DeskEvent::InputChanged {
                id: id.clone(),
                old: Some(Input::DisplayPort),
                new: Some(Input::Hdmi),
                by_this_host: true
            }],
            "{name}"
        );
        assert_eq!(desk.state(&id).unwrap().shows_this_host(), Some(false));
    }
}

#[test]
fn osd_changes_are_reported_as_external_on_both_monitors() {
    let (bus, h, mut desk) = desk_with(vec![lc34_dp(), FakeMonitorConfig::g5()]);
    desk.scan().unwrap();
    for (handle, name) in [(h[0], "LC34G55T"), (h[1], "Odyssey G5")] {
        bus.osd_switch(handle, Input::Hdmi);
        let events = desk.scan().unwrap();
        assert_eq!(
            events,
            vec![DeskEvent::InputChanged {
                id: id(&desk, name),
                old: Some(Input::DisplayPort),
                new: Some(Input::Hdmi),
                by_this_host: false
            }],
            "{name}"
        );
    }
}

#[test]
fn failed_switches_are_reported_on_both_monitors() {
    let mut big = lc34_dp();
    big.switch = SwitchBehavior::Fail;
    let mut small = FakeMonitorConfig::g5();
    small.switch = SwitchBehavior::Fail;
    let (_bus, _h, mut desk) = desk_with(vec![big, small]);
    desk.scan().unwrap();
    for name in ["LC34G55T", "Odyssey G5"] {
        let result = desk.switch(&id(&desk, name), Input::Hdmi, TIMEOUT).unwrap();
        assert_eq!(
            result,
            SwitchResult::Failed {
                target: Input::Hdmi,
                current: Some(Input::DisplayPort)
            },
            "{name}"
        );
    }
    assert!(
        desk.scan().unwrap().is_empty(),
        "a failed switch changed nothing"
    );
}

#[test]
fn power_button_off_and_on_is_tracked_and_debounced() {
    let (bus, h, mut desk) = desk_with(vec![lc34_dp(), FakeMonitorConfig::g5()]);
    desk.scan().unwrap();
    for (handle, name) in [(h[0], "LC34G55T"), (h[1], "Odyssey G5")] {
        let id = id(&desk, name);
        bus.power_button(handle, false);
        // One missed scan is not "off".
        assert!(desk.scan().unwrap().is_empty(), "{name}");
        assert!(!desk.state(&id).unwrap().off);
        assert_eq!(desk.state(&id).unwrap().presence, Presence::Absent);
        // Still missing after a short flap window: not off yet.
        bus.clock().advance(Duration::from_secs(3));
        assert!(desk.scan().unwrap().is_empty(), "{name}");
        assert_eq!(
            scan_past_debounce(&bus, &mut desk),
            vec![DeskEvent::Off { id: id.clone() }],
            "{name}"
        );
        let state = desk.state(&id).unwrap();
        assert!(state.off);
        assert_eq!(state.shows_this_host(), Some(false));
        // Off monitors refuse commands before any write.
        bus.clear_ops();
        assert!(matches!(
            desk.switch(&id, Input::Hdmi, TIMEOUT),
            Err(DdcError::NoChannel(_))
        ));
        assert!(sets(&bus, handle).is_empty());

        bus.power_button(handle, true);
        assert_eq!(
            desk.scan().unwrap(),
            vec![DeskEvent::Appeared { id: id.clone() }],
            "{name}"
        );
        let state = desk.state(&id).unwrap();
        assert!(!state.off);
        assert_eq!(state.status.unwrap().input, Some(Input::DisplayPort));
        let ops = bus.ops_for(handle);
        if name == "LC34G55T" {
            // A patched monitor is probed again before anything else (catches a firmware change).
            assert!(matches!(ops.first(), Some(BusOp::Get { code: 0xEA, .. })));
        } else {
            // A profiled one is the same unit: its capabilities are not read again (that read hangs
            // for about a minute while the G5 boots).
            assert!(
                !ops.iter()
                    .any(|op| matches!(op, BusOp::Capabilities { .. }))
            );
        }
    }
}

#[test]
fn link_flap_after_boot_is_not_off() {
    // The 34" left the PC's bus for ~3 s right after booting (2026-11-23): no Off, no Appeared.
    let (bus, h, mut desk) = desk_with(vec![lc34_dp()]);
    desk.scan().unwrap();
    bus.power_button(h[0], false);
    for _ in 0..6 {
        bus.clock().advance(Duration::from_millis(500));
        assert!(desk.scan().unwrap().is_empty());
    }
    bus.power_button(h[0], true);
    assert!(desk.scan().unwrap().is_empty());
    assert!(!by_name(&desk, "LC34G55T").off);
}

#[test]
fn a_failed_profile_check_is_retried_later_not_forever() {
    // A G5 whose capabilities read gives junk once (booting) must not stay "not compatible".
    let (bus, h, mut desk) = desk_with(vec![FakeMonitorConfig::g5()]);
    bus.set_personality(h[0], Personality::Garbage);
    desk.scan().unwrap();
    assert_eq!(by_name(&desk, "Odyssey G5").kind, None);
    bus.set_personality(h[0], Personality::G5Stock);
    desk.scan().unwrap();
    assert_eq!(by_name(&desk, "Odyssey G5").kind, None, "retried too early");
    bus.clock().advance(Duration::from_secs(31));
    desk.scan().unwrap();
    assert_eq!(by_name(&desk, "Odyssey G5").kind, Some("g5-falcon"));
}

#[test]
fn a_listed_monitor_in_standby_is_probed_only_every_ten_seconds() {
    let (bus, h, mut desk) = desk_with(vec![lc34_dp()]);
    desk.scan().unwrap();
    bus.set_personality(h[0], Personality::Disconnected); // listed, silent: standby
    desk.scan().unwrap();
    assert!(matches!(
        scan_past_debounce(&bus, &mut desk).as_slice(),
        [DeskEvent::Off { .. }]
    ));
    bus.clear_ops();
    for _ in 0..8 {
        bus.clock().advance(Duration::from_secs(1));
        desk.scan().unwrap();
    }
    let gets = bus
        .ops_for(h[0])
        .iter()
        .filter(|op| matches!(op, BusOp::Get { .. }))
        .count();
    // At most one probe (with its retries) in 8 s, instead of one every scan.
    assert!(gets <= 4, "{gets} Gets while in standby");
    bus.set_personality(h[0], Personality::Standard);
    bus.clock().advance(Duration::from_secs(10));
    assert!(matches!(
        desk.scan().unwrap().as_slice(),
        [DeskEvent::Appeared { .. }]
    ));
}

#[test]
fn single_lost_reply_is_not_off() {
    let (bus, h, mut desk) = desk_with(vec![lc34_dp()]);
    desk.scan().unwrap();
    bus.drop_next(h[0], 4); // one whole status read (all retries) fails
    assert!(desk.scan().unwrap().is_empty());
    let state = by_name(&desk, "LC34G55T");
    assert!(!state.off);
    assert_eq!(state.presence, Presence::Unreachable);
    assert!(desk.scan().unwrap().is_empty());
    assert_eq!(by_name(&desk, "LC34G55T").presence, Presence::Present);
}

#[test]
fn listed_but_silent_monitor_turns_off_after_the_debounce() {
    let (bus, h, mut desk) = desk_with(vec![FakeMonitorConfig::g5()]);
    desk.scan().unwrap();
    bus.set_personality(h[0], Personality::Disconnected);
    assert!(desk.scan().unwrap().is_empty());
    let events = scan_past_debounce(&bus, &mut desk);
    assert!(matches!(events.as_slice(), [DeskEvent::Off { .. }]));
    assert_eq!(by_name(&desk, "Odyssey G5").presence, Presence::Unreachable);
}

#[test]
fn power_commands_follow_each_models_capabilities() {
    let (bus, h, mut desk) = desk_with(vec![lc34_dp(), FakeMonitorConfig::g5()]);
    desk.scan().unwrap();
    let big = id(&desk, "LC34G55T");
    let small = id(&desk, "Odyssey G5");
    // G5 ignores 0xD6: refused before anything is sent.
    assert_eq!(
        desk.power_off(&small),
        Err(DdcError::Unsupported { code: 0xD6 })
    );
    assert!(sets(&bus, h[1]).is_empty());
    // Nobody can be woken by DDC.
    assert_eq!(
        desk.power_on(&big),
        Err(DdcError::Unsupported { code: 0xD6 })
    );
    assert_eq!(
        desk.power_on(&small),
        Err(DdcError::Unsupported { code: 0xD6 })
    );
    // The 34" goes to standby and leaves the bus, as measured.
    desk.power_off(&big).unwrap();
    assert_eq!(sets(&bus, h[0]), vec![(0xD6, 4)]);
    assert!(!bus.is_powered(h[0]));
    desk.scan().unwrap();
    assert_eq!(
        scan_past_debounce(&bus, &mut desk),
        vec![DeskEvent::Off { id: big.clone() }]
    );
    assert_eq!(
        desk.power_on(&big),
        Err(DdcError::Unsupported { code: 0xD6 })
    );
}

#[test]
fn incompatible_monitor_is_listed_and_never_written() {
    let mut other = FakeMonitorConfig::new(Personality::Factory);
    other.edid = test_edid("DEL", 0xD0C7, "DELL P2018H", "FAKE0000009");
    let (bus, h, mut desk) = desk_with(vec![other]);
    desk.scan().unwrap();
    desk.scan().unwrap();
    let state = by_name(&desk, "DELL P2018H");
    assert_eq!(state.kind, None);
    assert!(state.not_compatible);
    assert_eq!(state.shows_this_host(), None);
    assert!(desk.switch(&state.id, Input::Hdmi, TIMEOUT).is_err());
    assert!(sets(&bus, h[0]).is_empty());
}

#[test]
fn the_mac_side_sees_the_same_monitors_through_hdmi() {
    // On the Mac the monitors report their HDMI EDID ids: same ids, this host on HDMI.
    let mut big = FakeMonitorConfig::new(Personality::Standard);
    big.edid = test_edid("SAM", 0x7119, "LC34G55T", "FAKE0000001");
    big.connected_via = Input::Hdmi;
    let mut small = FakeMonitorConfig::g5();
    small.edid = test_edid("SAM", 0x748A, "Odyssey G5", "FAKE0000002");
    small.connected_via = Input::Hdmi;
    small.input = Input::Hdmi;
    let (_bus, _h, mut desk) = desk_with(vec![big, small]);
    desk.scan().unwrap();
    let big = by_name(&desk, "LC34G55T");
    assert_eq!(big.host_input, Some(Input::Hdmi));
    assert_eq!(big.shows_this_host(), Some(false)); // the 34" shows the PC on DP
    let small = by_name(&desk, "Odyssey G5");
    assert_eq!(small.kind, Some("g5-falcon"));
    assert_eq!(small.shows_this_host(), Some(true));
}
