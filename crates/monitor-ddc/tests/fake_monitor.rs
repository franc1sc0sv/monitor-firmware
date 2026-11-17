//! Protocol behaviour against the FakeMonitor personalities (no hardware).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use std::sync::Arc;
use std::time::Duration;

use monitor_ddc::fake::{
    BusOp, FakeBus, FakeClock, FakeMonitorConfig, Personality, SwitchBehavior, test_edid,
};
use monitor_ddc::{
    Clock, DdcBus, DdcError, EventKind, Incompatibility, Input, Link, MonitorHandle, Probe,
    StandardMonitor, VCP_RING, Verdict,
};
use proptest::prelude::*;

const TIMEOUT: Duration = Duration::from_secs(12);

fn bus() -> FakeBus {
    FakeBus::new(FakeClock::new())
}

fn link(bus: &FakeBus, h: MonitorHandle) -> Link {
    Link::new(Arc::new(bus.clone()), Arc::new(bus.clock()), h)
}

fn standard(bus: &FakeBus, config: FakeMonitorConfig) -> (MonitorHandle, StandardMonitor) {
    let h = bus.add(config);
    (h, link(bus, h).open_standard().unwrap())
}

fn only_probe_reads(ops: &[BusOp]) -> bool {
    ops.iter()
        .all(|op| matches!(op, BusOp::Get { code: VCP_RING, .. }))
}

#[test]
fn probe_by_personality() {
    let b = bus();
    let std = b.add(FakeMonitorConfig::new(Personality::Standard));
    let fac = b.add(FakeMonitorConfig::new(Personality::Factory));
    let off = b.add(FakeMonitorConfig::new(Personality::Disconnected));
    match link(&b, std).probe() {
        Probe::Compatible(info) => {
            assert_eq!((info.ring_size, info.protocol), (64, 2));
        }
        other => panic!("standard probed as {other:?}"),
    }
    assert_eq!(
        link(&b, fac).probe(),
        Probe::NotCompatible(Incompatibility::NoEventRing)
    );
    assert!(matches!(
        link(&b, off).probe(),
        Probe::NoChannel(DdcError::NoReply { code: VCP_RING })
    ));
}

#[test]
fn non_compatible_monitors_only_ever_see_the_probe_read() {
    let b = bus();
    let std = b.add(FakeMonitorConfig::new(Personality::Standard));
    let fac = b.add(FakeMonitorConfig::new(Personality::Factory));
    let off = b.add(FakeMonitorConfig::new(Personality::Disconnected));

    // What an agent does on every scan: enumerate, probe, open what is compatible, use it.
    let mut opened = Vec::new();
    for info in b.monitors().unwrap() {
        match link(&b, info.handle).open_standard() {
            Ok(m) => opened.push(m),
            Err(DdcError::NotCompatible(_) | DdcError::NoReply { .. }) => {}
            Err(e) => panic!("unexpected {e}"),
        }
    }
    assert_eq!(opened.len(), 1);
    let m = &opened[0];
    m.live().unwrap();
    let mut cursor = m.cursor().unwrap();
    m.read_events(&mut cursor).unwrap();
    assert!(matches!(
        m.switch_input(Input::Hdmi, TIMEOUT).unwrap(),
        Verdict::Confirmed { .. }
    ));

    for h in [fac, off] {
        let ops = b.ops_for(h);
        assert!(!ops.is_empty());
        assert!(
            only_probe_reads(&ops),
            "monitor {h} got more than Get 0xEA: {ops:?}"
        );
    }
    assert!(
        b.ops_for(std)
            .iter()
            .any(|op| matches!(op, BusOp::Set { code: 0x60, .. }))
    );
}

#[test]
fn factory_get_input_echoes_the_queried_port() {
    let b = bus();
    let mut config = FakeMonitorConfig::new(Personality::Factory);
    config.input = Input::Hdmi;
    config.connected_via = Input::DisplayPort;
    let h = b.add(config);
    // Reading 0x60 is allowed (read-only), but on stock firmware it is not the truth.
    assert_eq!(
        link(&b, h).get(0x60).unwrap().current,
        Input::DisplayPort.vcp()
    );
    assert_eq!(b.screen_input(h), Some(Input::Hdmi));
}

#[test]
fn switch_confirmed_by_the_firmware() {
    let b = bus();
    let (h, m) = standard(&b, FakeMonitorConfig::new(Personality::Standard));
    assert_eq!(m.input().unwrap(), Some(Input::DisplayPort));
    assert_eq!(
        m.switch_input(Input::Hdmi, TIMEOUT).unwrap(),
        Verdict::Confirmed {
            input: Some(Input::Hdmi)
        }
    );
    assert_eq!(b.screen_input(h), Some(Input::Hdmi));
    assert_eq!(m.input().unwrap(), Some(Input::Hdmi));
    assert_eq!(m.live().unwrap().input(), Some(Input::Hdmi));
    // And back, as every hardware test must do.
    assert_eq!(
        m.switch_input(Input::DisplayPort, TIMEOUT).unwrap(),
        Verdict::Confirmed {
            input: Some(Input::DisplayPort)
        }
    );
}

#[test]
fn switch_failed_by_the_firmware() {
    let b = bus();
    let mut config = FakeMonitorConfig::new(Personality::Standard);
    config.switch = SwitchBehavior::Fail;
    let (h, m) = standard(&b, config);
    assert_eq!(
        m.switch_input(Input::Hdmi, TIMEOUT).unwrap(),
        Verdict::Failed {
            target: Some(Input::Hdmi),
            current: Some(Input::DisplayPort)
        }
    );
    assert_eq!(b.screen_input(h), Some(Input::DisplayPort));
}

#[test]
fn switch_without_verdict_times_out() {
    let b = bus();
    let mut config = FakeMonitorConfig::new(Personality::Standard);
    config.switch = SwitchBehavior::Silent;
    let (_, m) = standard(&b, config);
    let start = b.clock().now();
    assert_eq!(
        m.switch_input(Input::Hdmi, TIMEOUT).unwrap(),
        Verdict::TimedOut
    );
    let waited = b.clock().now() - start;
    assert!(
        waited >= TIMEOUT && waited < TIMEOUT + Duration::from_secs(2),
        "waited {waited:?}"
    );
}

#[test]
fn switch_survives_a_retraining_link() {
    let b = bus();
    let mut config = FakeMonitorConfig::new(Personality::Standard);
    // More lost requests than one read retries: the wait loop itself must ride over them.
    config.retrain_drops = 12;
    let (_, m) = standard(&b, config);
    let mut cursor = m.cursor().unwrap();
    let start = b.clock().now();
    assert_eq!(
        m.switch_input(Input::Hdmi, TIMEOUT).unwrap(),
        Verdict::Confirmed {
            input: Some(Input::Hdmi)
        }
    );
    assert!(b.clock().now() - start < TIMEOUT);
    let kinds: Vec<_> = m
        .read_events(&mut cursor)
        .unwrap()
        .events
        .iter()
        .map(|e| e.kind())
        .collect();
    assert_eq!(
        kinds,
        [
            EventKind::DdcSwitchRequest,
            EventKind::InputPort,
            EventKind::SyncFlags,
            EventKind::SwitchDone
        ]
    );
}

#[test]
fn transient_errors_are_retried() {
    let b = bus();
    let (h, m) = standard(&b, FakeMonitorConfig::new(Personality::Standard));
    b.drop_next(h, 3);
    assert!(m.live().is_ok());
    b.drop_next(h, 10);
    assert_eq!(m.live(), Err(DdcError::NoReply { code: 0xEE }));
}

#[test]
fn osd_changes_show_as_input_port_without_request() {
    let b = bus();
    let (h, m) = standard(&b, FakeMonitorConfig::new(Personality::Standard));
    let mut cursor = m.cursor().unwrap();
    b.osd_switch(h, Input::Hdmi);
    let batch = m.read_events(&mut cursor).unwrap();
    assert_eq!(batch.lost, 0);
    assert_eq!(batch.events.len(), 1);
    let e = batch.events[0];
    assert_eq!((e.kind(), e.old, e.new), (EventKind::InputPort, 0, 1));
    assert!(m.read_events(&mut cursor).unwrap().events.is_empty());
}

#[test]
fn ring_overflow_reports_lost_events_across_the_sequence_wrap() {
    let b = bus();
    let (h, m) = standard(&b, FakeMonitorConfig::new(Personality::Standard));
    let mut cursor = m.cursor().unwrap();
    let n: u16 = 65_500;
    for i in 0..n {
        b.osd_switch(
            h,
            if i % 2 == 0 {
                Input::Hdmi
            } else {
                Input::DisplayPort
            },
        );
    }
    let batch = m.read_events(&mut cursor).unwrap();
    assert_eq!((batch.events.len(), batch.lost), (64, n - 64));
    for i in 0..100u16 {
        b.osd_switch(
            h,
            if i % 2 == 0 {
                Input::Hdmi
            } else {
                Input::DisplayPort
            },
        );
    }
    let before = cursor.last;
    let batch = m.read_events(&mut cursor).unwrap();
    assert_eq!(batch.lost, 36);
    assert_eq!(cursor.last, before.wrapping_add(100));
    assert!(
        batch
            .events
            .windows(2)
            .all(|w| w[1].seq == w[0].seq.wrapping_add(1))
    );
}

#[test]
fn monitors_are_listed_with_a_stable_id_and_capabilities() {
    let b = bus();
    let mut hdmi_side = FakeMonitorConfig::new(Personality::Factory);
    hdmi_side.edid = test_edid("SAM", 0x7156, "LC34G55T", "FAKE0000001");
    b.add(FakeMonitorConfig::new(Personality::Standard));
    b.add(hdmi_side);
    let list = b.monitors().unwrap();
    // The same physical monitor seen through DP and HDMI (different product codes) has one id.
    assert_eq!(list[0].id(), list[1].id());
    assert!(!list[0].id().unwrap().as_str().contains("FAKE0000001"));
    let caps = link(&b, list[0].handle).capabilities().unwrap();
    assert!(caps.contains("EA EB EC ED EE EF"));
}

#[test]
fn unknown_handles_are_reported() {
    let b = bus();
    let h = b.add(FakeMonitorConfig::new(Personality::Standard));
    b.remove(h);
    assert!(matches!(
        link(&b, h).probe(),
        Probe::NoChannel(DdcError::UnknownMonitor(_))
    ));
}

#[test]
fn event_kinds_keep_unknown_ids_and_setting_offsets() {
    assert_eq!(EventKind::from_id(0x99), EventKind::Unknown(0x99));
    let e = monitor_ddc::Event {
        seq: 1,
        id: 0x21,
        old: 0xD3,
        new: 99,
        time_10ms: 0,
    };
    assert_eq!(e.setting_offset(), Some(0x1D3));
}

proptest! {
    #[test]
    fn read_events_never_skips_or_repeats(bursts in proptest::collection::vec(0u16..150, 1..6)) {
        let b = bus();
        let (h, m) = standard(&b, FakeMonitorConfig::new(Personality::Standard));
        let mut cursor = m.cursor().unwrap();
        for n in bursts {
            let start = cursor.last;
            for i in 0..n {
                b.osd_switch(h, if i % 2 == 0 { Input::Hdmi } else { Input::DisplayPort });
            }
            let batch = m.read_events(&mut cursor).unwrap();
            let kept = n.min(64);
            prop_assert_eq!(batch.events.len(), usize::from(kept));
            prop_assert_eq!(batch.lost, n - kept);
            prop_assert_eq!(cursor.last, start.wrapping_add(n));
            prop_assert!(batch.events.iter().all(|e| e.kind() == EventKind::InputPort));
            prop_assert!(batch.events.windows(2).all(|w| w[1].seq == w[0].seq.wrapping_add(1)));
        }
    }
}
