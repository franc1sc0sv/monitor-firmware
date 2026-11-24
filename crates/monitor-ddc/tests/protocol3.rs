//! Protocol 3 (LC34 v3.2, G5 production image) through the same Monitor/Desk API (no hardware).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::sync::Arc;
use std::time::Duration;

use monitor_ddc::fake::{BusOp, FakeBus, FakeClock, FakeMonitorConfig, test_edid};
use monitor_ddc::{
    Clock, Desk, DeskEvent, EventKind, Input, Link, MonitorHandle, MonitorState, Power, Presence,
    SwitchResult,
};

const TIMEOUT: Duration = Duration::from_secs(10);

fn lc34() -> FakeMonitorConfig {
    let mut c = FakeMonitorConfig::lc34_v32();
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

#[test]
fn both_patched_monitors_announce_the_same_capabilities() {
    let (_bus, _h, mut desk) = desk_with(vec![lc34(), FakeMonitorConfig::g5_p3()]);
    desk.scan().unwrap();
    for name in ["LC34G55T", "Odyssey G5"] {
        let s = by_name(&desk, name);
        assert_eq!(s.kind, Some("standard"), "{name}");
        let caps = s.capabilities.unwrap();
        assert!(caps.power_on && caps.power_off, "{name}");
        assert!(caps.cable_detect && caps.switch_guard, "{name}");
        assert_eq!(s.status.unwrap().cable_mask, Some(0b11), "{name}");
    }
}

#[test]
fn soft_standby_keeps_the_monitor_reachable_and_wakes_by_command() {
    let (bus, h, mut desk) = desk_with(vec![lc34(), FakeMonitorConfig::g5_p3()]);
    desk.scan().unwrap();
    for (handle, name) in [(h[0], "LC34G55T"), (h[1], "Odyssey G5")] {
        let id = by_name(&desk, name).id;
        desk.power_off(&id).unwrap();
        assert!(bus.is_soft_standby(handle) && bus.is_powered(handle));
        assert_eq!(
            desk.scan().unwrap(),
            vec![DeskEvent::PowerChanged {
                id: id.clone(),
                power: Power::Standby
            }],
            "{name}"
        );
        let s = desk.state(&id).unwrap();
        assert_eq!(s.presence, Presence::Present);
        assert!(!s.off);
        assert_eq!(
            s.shows_this_host(),
            Some(false),
            "a dark panel shows nobody"
        );
        desk.power_on(&id).unwrap();
        assert!(!bus.is_soft_standby(handle));
        assert_eq!(
            desk.scan().unwrap(),
            vec![DeskEvent::PowerChanged {
                id: id.clone(),
                power: Power::On
            }],
            "{name}"
        );
    }
}

#[test]
fn switch_guard_refuses_an_input_without_cable_at_once() {
    let (bus, h, mut desk) = desk_with(vec![lc34()]);
    desk.scan().unwrap();
    let id = by_name(&desk, "LC34G55T").id;
    bus.set_cables(h[0], 0b01); // the Mac's HDMI cable is out
    assert_eq!(
        desk.scan().unwrap(),
        vec![DeskEvent::CablesChanged {
            id: id.clone(),
            mask: 0b01
        }]
    );
    let start = bus.clock().now();
    let result = desk.switch(&id, Input::Hdmi, TIMEOUT).unwrap();
    assert_eq!(
        result,
        SwitchResult::Failed {
            target: Input::Hdmi,
            current: Some(Input::DisplayPort)
        }
    );
    assert!(bus.clock().now() - start < Duration::from_secs(1));
    assert_eq!(bus.screen_input(h[0]), Some(Input::DisplayPort));
    assert_eq!(
        by_name(&desk, "LC34G55T")
            .status
            .unwrap()
            .cable(Input::Hdmi),
        Some(false)
    );
}

#[test]
fn patched_g5_switches_with_its_own_input_values() {
    let (bus, h, mut desk) = desk_with(vec![FakeMonitorConfig::g5_p3()]);
    desk.scan().unwrap();
    let id = by_name(&desk, "Odyssey G5").id;
    bus.clear_ops();
    assert_eq!(
        desk.switch(&id, Input::Hdmi, TIMEOUT).unwrap(),
        SwitchResult::Confirmed { input: Input::Hdmi }
    );
    assert!(bus.ops_for(h[0]).contains(&BusOp::Set {
        monitor: h[0],
        code: 0x60,
        value: 0x11
    }));
}

#[test]
fn power_and_cable_events_decode_from_the_ring() {
    let bus = FakeBus::new(FakeClock::new());
    let h = bus.add(lc34());
    let m = Link::new(Arc::new(bus.clone()), Arc::new(bus.clock()), h)
        .open_standard()
        .unwrap();
    assert_eq!(m.protocol(), 3);
    let mut cursor = m.cursor().unwrap();
    m.set_vcp(0xD6, 4).unwrap();
    bus.set_cables(h, 0b01);
    let kinds: Vec<_> = m
        .read_events(&mut cursor)
        .unwrap()
        .events
        .iter()
        .map(|e| (e.kind(), e.old, e.new))
        .collect();
    assert_eq!(
        kinds,
        vec![
            (EventKind::PowerState, 1, 4),
            (EventKind::CableMask, 0b11, 0b01)
        ]
    );
}
