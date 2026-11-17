//! The patched firmware's protocol (docs/protocol/vcp-interface.md, protocol version 2).
//!
//! The only way to get a [`StandardMonitor`] (and with it any Set or vendor code) is a successful
//! read-only probe: a monitor that is not compatible can be listed but never written to.

use std::fmt;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use crate::bus::{DdcBus, MonitorHandle, VcpReply};
use crate::clock::Clock;
use crate::error::DdcError;

pub const VCP_INPUT: u8 = 0x60;
pub const VCP_RING: u8 = 0xEA;
pub const VCP_CURSOR: u8 = 0xEB;
pub const VCP_RECORD: u8 = 0xEC;
pub const VCP_RECORD_TIME: u8 = 0xED;
pub const VCP_LIVE: u8 = 0xEE;
pub const VCP_CLOCK: u8 = 0xEF;
/// Oldest protocol version (Get 0xEA ML) this crate speaks.
pub const MIN_PROTOCOL: u8 = 2;

/// A monitor input, in the firmware's encoding.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Input {
    DisplayPort,
    Hdmi,
}

impl Input {
    /// Value for Get/Set 0x60 (Samsung encoding).
    pub fn vcp(self) -> u16 {
        match self {
            Input::DisplayPort => 0x09,
            Input::Hdmi => 0x06,
        }
    }

    /// Port number used by 0xEE and the events (0 DP, 1 HDMI).
    pub fn port(self) -> u8 {
        match self {
            Input::DisplayPort => 0,
            Input::Hdmi => 1,
        }
    }

    pub fn from_vcp(value: u16) -> Option<Self> {
        match value {
            0x09 => Some(Input::DisplayPort),
            0x06 => Some(Input::Hdmi),
            _ => None,
        }
    }

    pub fn from_port(port: u8) -> Option<Self> {
        match port {
            0 => Some(Input::DisplayPort),
            1 => Some(Input::Hdmi),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Input::DisplayPort => "dp",
            Input::Hdmi => "hdmi",
        }
    }
}

impl fmt::Display for Input {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for Input {
    type Err = DdcError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_ascii_lowercase().as_str() {
            "dp" | "displayport" => Ok(Input::DisplayPort),
            "hdmi" => Ok(Input::Hdmi),
            other => Err(DdcError::Protocol(format!("unknown input {other:?}"))),
        }
    }
}

/// Get 0xEA: the event ring.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RingInfo {
    pub ring_size: u8,
    pub protocol: u8,
    /// Sequence number of the newest event (16 bits, wraps).
    pub newest: u16,
}

impl RingInfo {
    fn from_reply(r: VcpReply) -> Self {
        Self {
            ring_size: r.mh(),
            protocol: r.ml(),
            newest: r.current,
        }
    }
}

/// Why a monitor is not compatible. Only reads were sent to find out.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Incompatibility {
    /// Get 0xEA is unsupported: stock firmware (or a monitor without the patch).
    NoEventRing,
    /// The ring answers, but with an older protocol version.
    OldProtocol(u8),
    /// The ring answers with size 0: not the firmware's ring.
    EmptyRing,
}

impl fmt::Display for Incompatibility {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Incompatibility::NoEventRing => f.write_str("VCP 0xEA unsupported (stock firmware)"),
            Incompatibility::OldProtocol(v) => {
                write!(f, "protocol {v}, need {MIN_PROTOCOL} or newer")
            }
            Incompatibility::EmptyRing => f.write_str("VCP 0xEA reports an empty event ring"),
        }
    }
}

/// Result of the read-only probe.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Probe {
    Compatible(RingInfo),
    NotCompatible(Incompatibility),
    /// The monitor did not answer at all (unplugged, powered off, inactive input on the Mac).
    NoChannel(DdcError),
}

/// Live state from Get 0xEE.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LiveState {
    pub port: u8,
    pub source_select: u8,
    pub power_flags: u8,
    pub signal: bool,
}

impl LiveState {
    /// The input on screen (the real one, not the port the query came in on).
    pub fn input(&self) -> Option<Input> {
        Input::from_port(self.port)
    }

    pub fn power_on(&self) -> bool {
        self.power_flags & 0x01 != 0
    }

    pub fn ddc_enabled(&self) -> bool {
        self.power_flags & 0x40 != 0
    }
}

/// Event ids (docs/protocol/vcp-interface.md, "Event ids"). Unknown ids are kept, never rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum EventKind {
    Boot,
    InputPort,
    SourceSelect,
    PowerFlags,
    PowersaveFlags,
    SyncFlags,
    Signal,
    SystemState,
    WindowPort,
    DdcSwitchRequest,
    SwitchDone,
    SwitchFailed,
    DdcPowerRequest,
    SettingChanged,
    Unknown(u8),
}

impl EventKind {
    pub fn from_id(id: u8) -> Self {
        match id {
            0x00 => EventKind::Boot,
            0x01 => EventKind::InputPort,
            0x02 => EventKind::SourceSelect,
            0x03 => EventKind::PowerFlags,
            0x04 => EventKind::PowersaveFlags,
            0x05 => EventKind::SyncFlags,
            0x06 => EventKind::Signal,
            0x07 => EventKind::SystemState,
            0x08 => EventKind::WindowPort,
            0x10 => EventKind::DdcSwitchRequest,
            0x11 => EventKind::SwitchDone,
            0x12 => EventKind::SwitchFailed,
            0x13 => EventKind::DdcPowerRequest,
            0x20 | 0x21 => EventKind::SettingChanged,
            other => EventKind::Unknown(other),
        }
    }

    pub fn name(&self) -> &'static str {
        match self {
            EventKind::Boot => "boot",
            EventKind::InputPort => "input-port",
            EventKind::SourceSelect => "source-select",
            EventKind::PowerFlags => "power-flags",
            EventKind::PowersaveFlags => "powersave-flags",
            EventKind::SyncFlags => "sync-flags",
            EventKind::Signal => "signal",
            EventKind::SystemState => "system-state",
            EventKind::WindowPort => "window-port",
            EventKind::DdcSwitchRequest => "ddc-switch-request",
            EventKind::SwitchDone => "switch-done",
            EventKind::SwitchFailed => "switch-failed",
            EventKind::DdcPowerRequest => "ddc-power-request",
            EventKind::SettingChanged => "setting-changed",
            EventKind::Unknown(_) => "unknown",
        }
    }
}

/// One record of the firmware's event ring.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Event {
    pub seq: u16,
    pub id: u8,
    pub old: u8,
    pub new: u8,
    /// 10 ms units since the monitor booted (24 bits).
    pub time_10ms: u32,
}

impl Event {
    pub fn kind(&self) -> EventKind {
        EventKind::from_id(self.id)
    }

    /// For `setting-changed`: offset from 0x204000 (bit 8 travels in the id's bit 0).
    pub fn setting_offset(&self) -> Option<u16> {
        (self.kind() == EventKind::SettingChanged)
            .then(|| (u16::from(self.id & 1) << 8) | u16::from(self.old))
    }
}

/// Client-side position in the event stream: the last sequence number already read.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventCursor {
    pub last: u16,
}

/// Events read in one call. `lost > 0` means the ring overflowed since the previous read.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct EventBatch {
    pub events: Vec<Event>,
    pub lost: u16,
}

/// Firmware verdict for an input switch.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    /// `switch-done`: the target is on screen with a locked picture.
    Confirmed { input: Option<Input> },
    /// `switch-failed`: no locked picture on the target; `current` is what the monitor shows.
    Failed {
        target: Option<Input>,
        current: Option<Input>,
    },
    /// No verdict before the deadline (for example asked over an input the monitor stopped answering on).
    TimedOut,
}

/// Retry and polling knobs. Defaults follow the protocol rules (50-150 ms between request and reply is
/// the backend's job; these are the waits between whole requests).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LinkConfig {
    pub attempts: u32,
    pub retry_delay: Duration,
    pub poll_interval: Duration,
}

impl Default for LinkConfig {
    fn default() -> Self {
        Self {
            attempts: 4,
            retry_delay: Duration::from_millis(30),
            poll_interval: Duration::from_millis(100),
        }
    }
}

/// A monitor reachable through a bus, before anything is known about it. It can only read.
#[derive(Clone)]
pub struct Link {
    bus: Arc<dyn DdcBus>,
    clock: Arc<dyn Clock>,
    handle: MonitorHandle,
    config: LinkConfig,
}

impl Link {
    pub fn new(bus: Arc<dyn DdcBus>, clock: Arc<dyn Clock>, handle: MonitorHandle) -> Self {
        Self {
            bus,
            clock,
            handle,
            config: LinkConfig::default(),
        }
    }

    pub fn with_config(mut self, config: LinkConfig) -> Self {
        self.config = config;
        self
    }

    pub fn handle(&self) -> MonitorHandle {
        self.handle
    }

    /// Get VCP with retries on transient errors. Reading is always safe, compatible or not.
    pub fn get(&self, code: u8) -> Result<VcpReply, DdcError> {
        self.retry(|| self.bus.get_vcp(self.handle, code))
    }

    pub fn capabilities(&self) -> Result<String, DdcError> {
        self.retry(|| self.bus.capabilities(self.handle))
    }

    /// Read-only probe: Get 0xEA and nothing else.
    pub fn probe(&self) -> Probe {
        match self.get(VCP_RING) {
            Ok(reply) => {
                let info = RingInfo::from_reply(reply);
                if info.protocol < MIN_PROTOCOL {
                    Probe::NotCompatible(Incompatibility::OldProtocol(info.protocol))
                } else if info.ring_size == 0 {
                    Probe::NotCompatible(Incompatibility::EmptyRing)
                } else {
                    Probe::Compatible(info)
                }
            }
            Err(DdcError::Unsupported { .. }) => Probe::NotCompatible(Incompatibility::NoEventRing),
            Err(e) => Probe::NoChannel(e),
        }
    }

    /// Probes and, only if compatible, returns the controllable monitor.
    pub fn open_standard(self) -> Result<StandardMonitor, DdcError> {
        match self.probe() {
            Probe::Compatible(info) => Ok(StandardMonitor {
                link: self,
                protocol: info.protocol,
            }),
            Probe::NotCompatible(why) => Err(DdcError::NotCompatible(why)),
            Probe::NoChannel(e) => Err(e),
        }
    }

    fn set(&self, code: u8, value: u16) -> Result<(), DdcError> {
        self.retry(|| self.bus.set_vcp(self.handle, code, value))
    }

    fn retry<T>(&self, mut op: impl FnMut() -> Result<T, DdcError>) -> Result<T, DdcError> {
        let mut attempt = 1;
        loop {
            match op() {
                Err(e) if e.is_transient() && attempt < self.config.attempts => {
                    attempt += 1;
                    self.clock.sleep(self.config.retry_delay);
                }
                other => return other,
            }
        }
    }
}

/// A monitor confirmed to speak the firmware protocol.
#[derive(Clone)]
pub struct StandardMonitor {
    link: Link,
    protocol: u8,
}

impl StandardMonitor {
    pub fn handle(&self) -> MonitorHandle {
        self.link.handle
    }

    pub fn protocol(&self) -> u8 {
        self.protocol
    }

    pub fn ring_info(&self) -> Result<RingInfo, DdcError> {
        self.link.get(VCP_RING).map(RingInfo::from_reply)
    }

    pub fn live(&self) -> Result<LiveState, DdcError> {
        let r = self.link.get(VCP_LIVE)?;
        Ok(LiveState {
            port: r.mh(),
            source_select: r.ml(),
            power_flags: r.ch(),
            signal: r.cl() != 0,
        })
    }

    /// Monitor clock, 10 ms units since boot.
    pub fn clock_10ms(&self) -> Result<u32, DdcError> {
        let r = self.link.get(VCP_CLOCK)?;
        Ok((u32::from(r.max) << 16) | u32::from(r.current))
    }

    /// Get 0x60: with the firmware this is the input on screen.
    pub fn input(&self) -> Result<Option<Input>, DdcError> {
        Ok(Input::from_vcp(self.link.get(VCP_INPUT)?.current & 0xFF))
    }

    pub fn get_vcp(&self, code: u8) -> Result<VcpReply, DdcError> {
        self.link.get(code)
    }

    /// Plain Set VCP (no read-back). For inputs use [`Self::switch_input`].
    pub fn set_vcp(&self, code: u8, value: u16) -> Result<(), DdcError> {
        self.link.set(code, value)
    }

    pub fn capabilities(&self) -> Result<String, DdcError> {
        self.link.capabilities()
    }

    /// Reads one record. Valid only when both 0xEC CL and 0xED MH match the cursor's low byte.
    pub fn event(&self, seq: u16) -> Result<Event, DdcError> {
        let low = seq.to_be_bytes()[1];
        for _ in 0..self.link.config.attempts {
            self.link.set(VCP_CURSOR, seq)?;
            let rec = self.link.get(VCP_RECORD)?;
            let time = self.link.get(VCP_RECORD_TIME)?;
            if rec.cl() == low && time.mh() == low {
                return Ok(Event {
                    seq,
                    id: rec.mh(),
                    old: rec.ml(),
                    new: rec.ch(),
                    time_10ms: (u32::from(time.ml()) << 16) | u32::from(time.current),
                });
            }
        }
        Err(DdcError::Protocol(format!("event #{seq} never validated")))
    }

    /// A cursor at the newest event: the next read returns only what happens from now on.
    pub fn cursor(&self) -> Result<EventCursor, DdcError> {
        Ok(EventCursor {
            last: self.ring_info()?.newest,
        })
    }

    /// Reads every event after `cursor` and advances it. The cursor only moves when the whole batch was
    /// read, so after an error the next call reads the same events again instead of skipping them.
    pub fn read_events(&self, cursor: &mut EventCursor) -> Result<EventBatch, DdcError> {
        let info = self.ring_info()?;
        let ring = u16::from(info.ring_size);
        let mut last = cursor.last;
        let mut gap = info.newest.wrapping_sub(last);
        let mut lost = 0;
        if gap > ring {
            lost = gap - ring;
            last = info.newest.wrapping_sub(ring);
            gap = ring;
        }
        let mut events = Vec::with_capacity(usize::from(gap));
        for _ in 0..gap {
            last = last.wrapping_add(1);
            events.push(self.event(last)?);
        }
        cursor.last = last;
        Ok(EventBatch { events, lost })
    }

    /// Set 0x60 and wait for the firmware's own verdict (`switch-done` / `switch-failed`).
    /// Read errors while waiting are expected (the link retrains) and only end the wait at the deadline.
    pub fn switch_input(&self, target: Input, timeout: Duration) -> Result<Verdict, DdcError> {
        let clock = &self.link.clock;
        let mut last = self.ring_info()?.newest;
        self.link.set(VCP_INPUT, target.vcp())?;
        let deadline = clock.now() + timeout;
        while clock.now() < deadline {
            clock.sleep(self.link.config.poll_interval);
            let Ok(info) = self.ring_info() else { continue };
            while last != info.newest {
                let next = last.wrapping_add(1);
                let Ok(e) = self.event(next) else { break };
                last = next;
                match e.kind() {
                    EventKind::SwitchDone => {
                        return Ok(Verdict::Confirmed {
                            input: Input::from_port(e.new),
                        });
                    }
                    EventKind::SwitchFailed => {
                        return Ok(Verdict::Failed {
                            target: Input::from_port(e.old),
                            current: Input::from_port(e.new),
                        });
                    }
                    _ => {}
                }
            }
        }
        Ok(Verdict::TimedOut)
    }
}
