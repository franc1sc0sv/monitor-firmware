//! Stock monitors controlled through a profile (ADR-0020), and the two-monitor desk (no hardware).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::sync::Arc;
use std::time::Duration;

use monitor_ddc::fake::{BusOp, FakeBus, FakeClock, FakeMonitorConfig, Personality, test_edid};
use monitor_ddc::{
    DdcBus, Input, Link, MonitorHandle, MonitorInfo, Opened, ProfiledVerdict, Verdict, open,
};

const TIMEOUT: Duration = Duration::from_secs(8);

fn bus() -> FakeBus {
    FakeBus::new(FakeClock::new())
}

fn info(bus: &FakeBus, h: MonitorHandle) -> MonitorInfo {
    bus.monitors()
        .unwrap()
        .into_iter()
        .find(|m| m.handle == h)
        .unwrap()
}

fn opened(bus: &FakeBus, h: MonitorHandle) -> Opened {
    let link = Link::new(Arc::new(bus.clone()), Arc::new(bus.clock()), h);
    open(link, &info(bus, h))
}

fn no_sets(ops: &[BusOp]) -> bool {
    !ops.iter().any(|op| matches!(op, BusOp::Set { .. }))
}

#[test]
fn stock_g5_opens_through_its_profile_with_reads_only() {
    let b = bus();
    let h = b.add(FakeMonitorConfig::g5());
    let Opened::Profiled(m) = opened(&b, h) else {
        panic!("G5 did not open as profiled");
    };
    assert_eq!(m.profile().key, "g5-falcon");
    assert!(no_sets(&b.ops_for(h)), "a Set was sent before the checks");
    assert_eq!(m.input().unwrap(), Some(Input::DisplayPort));
}

#[test]
fn unknown_stock_monitor_is_never_written_to() {
    let b = bus();
    let h = b.add(FakeMonitorConfig::new(Personality::Factory));
    assert!(matches!(opened(&b, h), Opened::NotCompatible(_)));
    assert!(no_sets(&b.ops_for(h)));
}

#[test]
fn g5_edid_with_foreign_capabilities_is_rejected() {
    let b = bus();
    let mut cfg = FakeMonitorConfig::new(Personality::Factory);
    cfg.edid = test_edid("SAM", 0x7489, "Odyssey G5", "FAKE0000003");
    let h = b.add(cfg);
    assert!(matches!(opened(&b, h), Opened::NotCompatible(_)));
    assert!(no_sets(&b.ops_for(h)));
}

#[test]
fn powered_off_g5_reports_no_channel() {
    let b = bus();
    let mut cfg = FakeMonitorConfig::g5();
    cfg.personality = Personality::Disconnected;
    let h = b.add(cfg);
    assert!(matches!(opened(&b, h), Opened::NoChannel(_)));
    assert!(no_sets(&b.ops_for(h)));
}

#[test]
fn g5_switch_is_accepted_and_sends_only_the_profile_value() {
    let b = bus();
    let mut cfg = FakeMonitorConfig::g5();
    cfg.input = Input::Hdmi;
    let h = b.add(cfg);
    let Opened::Profiled(mut m) = opened(&b, h) else {
        panic!("not profiled");
    };
    b.clear_ops();
    let verdict = m.switch_input(Input::DisplayPort, TIMEOUT).unwrap();
    assert_eq!(
        verdict,
        ProfiledVerdict::Accepted {
            input: Input::DisplayPort
        }
    );
    let sets: Vec<_> = b
        .ops_for(h)
        .into_iter()
        .filter(|op| matches!(op, BusOp::Set { .. }))
        .collect();
    assert_eq!(
        sets,
        vec![BusOp::Set {
            monitor: h,
            code: 0x60,
            value: 0x0F
        }]
    );
    // The picture follows after the switch delay.
    b.clock().advance(Duration::from_secs(2));
    assert_eq!(b.screen_input(h), Some(Input::DisplayPort));
}

#[test]
fn g5_poll_sees_an_osd_input_change() {
    let b = bus();
    let h = b.add(FakeMonitorConfig::g5());
    let Opened::Profiled(mut m) = opened(&b, h) else {
        panic!("not profiled");
    };
    assert_eq!(m.poll().unwrap(), None);
    b.osd_switch(h, Input::Hdmi);
    let change = m.poll().unwrap().unwrap();
    assert_eq!(
        (change.old, change.new),
        (Some(Input::DisplayPort), Some(Input::Hdmi))
    );
    assert_eq!(m.poll().unwrap(), None);
}

#[test]
fn desk_with_both_monitors() {
    let b = bus();
    let lc34 = b.add(FakeMonitorConfig::new(Personality::Standard));
    let g5 = b.add(FakeMonitorConfig::g5());
    let Opened::Standard(big) = opened(&b, lc34) else {
        panic!("34 not standard");
    };
    let Opened::Profiled(mut small) = opened(&b, g5) else {
        panic!("G5 not profiled");
    };
    assert_eq!(
        big.switch_input(Input::Hdmi, TIMEOUT).unwrap(),
        Verdict::Confirmed {
            input: Some(Input::Hdmi)
        }
    );
    assert!(no_sets(&b.ops_for(g5)), "switching the 34 touched the G5");
    b.clear_ops();
    assert_eq!(
        small.switch_input(Input::Hdmi, TIMEOUT).unwrap(),
        ProfiledVerdict::Accepted { input: Input::Hdmi }
    );
    // The G5 never receives the patched protocol's vendor codes.
    assert!(
        !b.ops_for(g5)
            .iter()
            .any(|op| matches!(op, BusOp::Set { code, .. } if *code >= 0xE0))
    );
    assert!(no_sets(&b.ops_for(lc34)));
}
