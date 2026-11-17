//! Test double of the patched firmware (the Rust twin of `client/src/monitor_events/simulate.py`).
//!
//! Deterministic: time only moves when someone sleeps on the shared [`FakeClock`], so a 12 s timeout
//! runs in microseconds. Every request is recorded, which lets tests prove that a non-compatible monitor
//! never receives a Set or a vendor code.

use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use crate::bus::{DdcBus, MonitorHandle, MonitorInfo, VcpReply};
use crate::clock::Clock;
use crate::edid::Edid;
use crate::error::DdcError;
use crate::protocol::{Input, VCP_INPUT};

const RING: usize = 64;

/// Virtual monotonic clock shared by the fake monitors and the code under test.
#[derive(Debug, Clone, Default)]
pub struct FakeClock {
    now: Arc<Mutex<Duration>>,
}

impl FakeClock {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn advance(&self, by: Duration) {
        *lock(&self.now) += by;
    }
}

impl Clock for FakeClock {
    fn now(&self) -> Duration {
        *lock(&self.now)
    }

    fn sleep(&self, duration: Duration) {
        self.advance(duration);
    }
}

/// How a fake monitor behaves.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Personality {
    /// Patched firmware v3 (protocol 2): event ring, verdicts, truthful 0x60.
    Standard,
    /// Stock firmware: no 0xEA..0xEF, Get 0x60 echoes the port the query came in on, switches silently.
    Factory,
    /// Listed by the OS but never answers (powered off, inactive input).
    Disconnected,
    /// Stock firmware that answers every Get with result code 0 and the same junk
    /// ([`FakeMonitorConfig::garbage`]), as some monitors do for codes they do not know.
    Garbage,
}

/// What a standard monitor does after a Set 0x60.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SwitchBehavior {
    /// Changes input, locks the picture, logs `switch-done`.
    Done,
    /// Stays where it is and logs `switch-failed`.
    Fail,
    /// Changes input but never logs a verdict.
    Silent,
}

#[derive(Debug, Clone)]
pub struct FakeMonitorConfig {
    pub personality: Personality,
    pub description: String,
    pub edid: Vec<u8>,
    /// Input on screen at start.
    pub input: Input,
    /// Input the host's DDC requests arrive on (what a stock Get 0x60 reports).
    pub connected_via: Input,
    pub switch_delay: Duration,
    pub switch: SwitchBehavior,
    /// Requests lost right after a Set 0x60 (the link retrains while the input changes).
    pub retrain_drops: u32,
    /// What a [`Personality::Garbage`] monitor answers to every Get.
    pub garbage: VcpReply,
}

impl FakeMonitorConfig {
    /// The 34" LC34G55T with a fictitious serial.
    pub fn new(personality: Personality) -> Self {
        Self {
            personality,
            description: "fake LC34G55T".into(),
            edid: test_edid("SAM", 0x7155, "LC34G55T", "FAKE0000001"),
            input: Input::DisplayPort,
            connected_via: Input::DisplayPort,
            switch_delay: Duration::from_millis(300),
            switch: SwitchBehavior::Done,
            retrain_drops: 0,
            garbage: VcpReply {
                max: 0xFF05,
                current: 0x1234,
            },
        }
    }
}

/// One request seen by the fake bus.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BusOp {
    Get {
        monitor: MonitorHandle,
        code: u8,
    },
    Set {
        monitor: MonitorHandle,
        code: u8,
        value: u16,
    },
    Capabilities {
        monitor: MonitorHandle,
    },
}

impl BusOp {
    pub fn monitor(&self) -> MonitorHandle {
        match *self {
            BusOp::Get { monitor, .. }
            | BusOp::Set { monitor, .. }
            | BusOp::Capabilities { monitor } => monitor,
        }
    }
}

#[derive(Debug, Clone, Copy, Default)]
struct Record {
    seq: u16,
    id: u8,
    old: u8,
    new: u8,
    time: u32,
}

#[derive(Debug, Clone, Copy)]
enum Pending {
    Arrive(Input),
    Fail(Input),
    Change(Input),
}

#[derive(Debug)]
struct FakeMonitor {
    handle: MonitorHandle,
    config: FakeMonitorConfig,
    input: Input,
    seq: u16,
    ring: [Record; RING],
    cursor: u16,
    brightness: u16,
    pending: Vec<(Duration, Pending)>,
    /// Requests still to drop with no reply (a link retraining, a noisy cable).
    drop_next: u32,
    /// When the monitor last booted: its clock and event times count from here.
    booted_at: Duration,
}

impl FakeMonitor {
    fn new(handle: MonitorHandle, config: FakeMonitorConfig, now: Duration) -> Self {
        let mut m = Self {
            handle,
            input: config.input,
            config,
            seq: 0,
            ring: [Record::default(); RING],
            cursor: 0,
            brightness: 80,
            pending: Vec::new(),
            drop_next: 0,
            booted_at: now,
        };
        m.log(now, 0x00, 0, 0);
        m
    }

    fn log(&mut self, now: Duration, id: u8, old: u8, new: u8) {
        self.seq = self.seq.wrapping_add(1);
        let time = ((now.saturating_sub(self.booted_at).as_millis() / 10) & 0xFF_FFFF) as u32;
        self.ring[usize::from(self.seq) % RING] = Record {
            seq: self.seq,
            id,
            old,
            new,
            time,
        };
    }

    fn set_input(&mut self, now: Duration, to: Input) {
        let old = self.input.port();
        self.input = to;
        self.log(now, 0x01, old, to.port());
    }

    /// Applies everything due by `now`, in order.
    fn tick(&mut self, now: Duration) {
        self.pending.sort_by_key(|(due, _)| *due);
        while self.pending.first().is_some_and(|(due, _)| *due <= now) {
            let (due, action) = self.pending.remove(0);
            match action {
                Pending::Arrive(to) => {
                    self.set_input(due, to);
                    self.log(due, 0x05, 0x0E, 0x0A);
                    self.log(due, 0x11, to.port(), to.port());
                }
                Pending::Fail(to) => {
                    let cur = self.input.port();
                    self.log(due, 0x12, to.port(), cur);
                }
                Pending::Change(to) => self.set_input(due, to),
            }
        }
    }

    fn standard(&self) -> bool {
        self.config.personality == Personality::Standard
    }

    /// True when this request is lost on the wire.
    fn dropped(&mut self) -> bool {
        if self.config.personality == Personality::Disconnected {
            return true;
        }
        let drop = self.drop_next > 0;
        self.drop_next = self.drop_next.saturating_sub(1);
        drop
    }

    /// Power cycle: RAM is lost, the sequence starts over and the clock restarts.
    fn reboot(&mut self, now: Duration) {
        self.seq = 0;
        self.ring = [Record::default(); RING];
        self.cursor = 0;
        self.pending.clear();
        self.booted_at = now;
        self.log(now, 0x00, 0, 0);
    }

    fn get(&mut self, code: u8, now: Duration) -> Result<VcpReply, DdcError> {
        if self.dropped() {
            return Err(DdcError::NoReply { code });
        }
        if self.config.personality == Personality::Garbage {
            return Ok(self.config.garbage);
        }
        let r = VcpReply::from_bytes;
        let rec = self.ring[usize::from(self.cursor) % RING];
        let clock = ((now.saturating_sub(self.booted_at).as_millis() / 10) & 0xFFFF_FFFF) as u32;
        match code {
            0x10 => Ok(VcpReply {
                max: 100,
                current: self.brightness,
            }),
            VCP_INPUT if self.standard() => Ok(VcpReply {
                max: 0x0E,
                current: self.input.vcp(),
            }),
            VCP_INPUT => Ok(VcpReply {
                max: 0x0E,
                current: self.config.connected_via.vcp(),
            }),
            _ if !self.standard() => Err(DdcError::Unsupported { code }),
            0xEA => Ok(VcpReply {
                max: u16::from_be_bytes([RING as u8, 2]),
                current: self.seq,
            }),
            0xEB => Ok(VcpReply {
                max: 0,
                current: self.cursor,
            }),
            0xEC => Ok(r(rec.id, rec.old, rec.new, rec.seq.to_be_bytes()[1])),
            0xED => {
                let t = rec.time.to_be_bytes();
                Ok(r(rec.seq.to_be_bytes()[1], t[1], t[2], t[3]))
            }
            0xEE => Ok(r(
                self.input.port(),
                if self.input == Input::Hdmi { 2 } else { 1 },
                0x41,
                1,
            )),
            0xEF => {
                let t = clock.to_be_bytes();
                Ok(r(t[0], t[1], t[2], t[3]))
            }
            _ => Err(DdcError::Unsupported { code }),
        }
    }

    fn set(&mut self, code: u8, value: u16, now: Duration) -> Result<(), DdcError> {
        if self.dropped() {
            return Err(DdcError::NoReply { code });
        }
        match code {
            0x10 => self.brightness = value.min(100),
            VCP_INPUT => {
                // Unknown input values are ignored, like the firmware does.
                let Some(to) = Input::from_vcp(value) else {
                    return Ok(());
                };
                let due = now + self.config.switch_delay;
                self.drop_next = self.config.retrain_drops;
                if self.standard() {
                    self.log(now, 0x10, self.input.port(), value.to_be_bytes()[1]);
                    let action = match self.config.switch {
                        SwitchBehavior::Done => Pending::Arrive(to),
                        SwitchBehavior::Fail => Pending::Fail(to),
                        SwitchBehavior::Silent => Pending::Change(to),
                    };
                    self.pending.push((due, action));
                } else {
                    self.pending.push((due, Pending::Change(to)));
                }
            }
            0xEB if self.standard() => self.cursor = value,
            // Writes to unknown codes have no acknowledgement on the wire: accepted and ignored.
            _ => {}
        }
        Ok(())
    }

    fn capabilities(&self) -> Result<String, DdcError> {
        let vcp = match self.config.personality {
            Personality::Disconnected => return Err(DdcError::NoReply { code: 0xF3 }),
            Personality::Garbage => return Ok("\u{fffd}".into()),
            Personality::Standard => {
                "02 04 05 08 10 12 14(05 08 0B) 16 18 1A 60(06 09) D6(01 05) EA EB EC ED EE EF"
            }
            Personality::Factory => "02 04 05 08 10 12 14(05 08 0B) 16 18 1A 60(06 09) D6(01 05)",
        };
        Ok(format!(
            "(prot(monitor)type(LCD)model(LC34G55T)cmds(01 02 03 07 0C E3 F3)vcp({vcp})mccs_ver(2.1))"
        ))
    }
}

#[derive(Debug, Default)]
struct State {
    monitors: Vec<FakeMonitor>,
    ops: Vec<BusOp>,
    next: u64,
}

/// A bus with any number of fake monitors.
#[derive(Debug, Clone)]
pub struct FakeBus {
    clock: FakeClock,
    state: Arc<Mutex<State>>,
}

impl FakeBus {
    pub fn new(clock: FakeClock) -> Self {
        Self {
            clock,
            state: Arc::default(),
        }
    }

    pub fn clock(&self) -> FakeClock {
        self.clock.clone()
    }

    pub fn add(&self, config: FakeMonitorConfig) -> MonitorHandle {
        let mut s = lock(&self.state);
        s.next += 1;
        let handle = MonitorHandle(s.next);
        let now = self.clock.now();
        s.monitors.push(FakeMonitor::new(handle, config, now));
        handle
    }

    pub fn remove(&self, handle: MonitorHandle) {
        lock(&self.state).monitors.retain(|m| m.handle != handle);
    }

    /// Every request so far, in order.
    pub fn ops(&self) -> Vec<BusOp> {
        lock(&self.state).ops.clone()
    }

    pub fn ops_for(&self, handle: MonitorHandle) -> Vec<BusOp> {
        self.ops()
            .into_iter()
            .filter(|op| op.monitor() == handle)
            .collect()
    }

    pub fn clear_ops(&self) {
        lock(&self.state).ops.clear();
    }

    /// Input actually on screen (the truth, whatever the monitor reports).
    pub fn screen_input(&self, handle: MonitorHandle) -> Option<Input> {
        let now = self.clock.now();
        self.with(handle, |m| {
            m.tick(now);
            Ok(m.input)
        })
        .ok()
    }

    /// The user changes the input with the OSD: an `input-port` event without a DDC request.
    pub fn osd_switch(&self, handle: MonitorHandle, to: Input) {
        let now = self.clock.now();
        let _ = self.with(handle, |m| {
            m.tick(now);
            m.set_input(now, to);
            Ok(())
        });
    }

    /// Power-cycles the monitor (sequence back to 0, empty ring, `boot` event).
    pub fn reboot(&self, handle: MonitorHandle) {
        let now = self.clock.now();
        let _ = self.with(handle, |m| {
            m.reboot(now);
            Ok(())
        });
    }

    /// The next `count` requests to this monitor get no reply.
    pub fn drop_next(&self, handle: MonitorHandle, count: u32) {
        let _ = self.with(handle, |m| {
            m.drop_next = count;
            Ok(())
        });
    }

    pub fn set_personality(&self, handle: MonitorHandle, personality: Personality) {
        let _ = self.with(handle, |m| {
            m.config.personality = personality;
            Ok(())
        });
    }

    fn with<T>(
        &self,
        handle: MonitorHandle,
        f: impl FnOnce(&mut FakeMonitor) -> Result<T, DdcError>,
    ) -> Result<T, DdcError> {
        let mut s = lock(&self.state);
        let m = s
            .monitors
            .iter_mut()
            .find(|m| m.handle == handle)
            .ok_or(DdcError::UnknownMonitor(handle))?;
        f(m)
    }

    fn record(&self, op: BusOp) {
        lock(&self.state).ops.push(op);
    }
}

impl DdcBus for FakeBus {
    fn monitors(&self) -> Result<Vec<MonitorInfo>, DdcError> {
        let s = lock(&self.state);
        Ok(s.monitors
            .iter()
            .map(|m| MonitorInfo {
                handle: m.handle,
                description: m.config.description.clone(),
                edid: Edid::parse(&m.config.edid).ok(),
            })
            .collect())
    }

    fn get_vcp(&self, monitor: MonitorHandle, code: u8) -> Result<VcpReply, DdcError> {
        self.record(BusOp::Get { monitor, code });
        let now = self.clock.now();
        self.with(monitor, |m| {
            m.tick(now);
            m.get(code, now)
        })
    }

    fn set_vcp(&self, monitor: MonitorHandle, code: u8, value: u16) -> Result<(), DdcError> {
        self.record(BusOp::Set {
            monitor,
            code,
            value,
        });
        let now = self.clock.now();
        self.with(monitor, |m| {
            m.tick(now);
            m.set(code, value, now)
        })
    }

    fn capabilities(&self, monitor: MonitorHandle) -> Result<String, DdcError> {
        self.record(BusOp::Capabilities { monitor });
        self.with(monitor, |m| m.capabilities())
    }
}

/// A valid 128-byte EDID with the given identity (for tests and the simulator; use fictitious serials).
pub fn test_edid(manufacturer: &str, product: u16, name: &str, serial: &str) -> Vec<u8> {
    let mut e = vec![0u8; 128];
    e[..8].copy_from_slice(&[0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00]);
    let letters: Vec<u16> = manufacturer
        .bytes()
        .map(|b| u16::from(b.saturating_sub(b'@') & 0x1F))
        .collect();
    let packed = letters.iter().fold(0u16, |acc, l| (acc << 5) | l);
    e[8..10].copy_from_slice(&packed.to_be_bytes());
    e[10..12].copy_from_slice(&product.to_le_bytes());
    e[18] = 1;
    e[19] = 4;
    for (at, tag, text) in [(72, 0xFC, name), (90, 0xFF, serial)] {
        e[at + 3] = tag;
        let field = &mut e[at + 5..at + 18];
        field.fill(b' ');
        let bytes = text.as_bytes();
        let n = bytes.len().min(13);
        field[..n].copy_from_slice(&bytes[..n]);
        if n < 13 {
            field[n] = 0x0A;
        }
    }
    let sum = e[..127].iter().fold(0u8, |a, b| a.wrapping_add(*b));
    e[127] = 0u8.wrapping_sub(sum);
    e
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    // A panic in another test thread must not cascade: the data is still usable for a double.
    m.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}
