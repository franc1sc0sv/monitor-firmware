//! Every monitor this host can see, tracked across scans by [`MonitorId`]: which input each shows, whether
//! that is this host, when it changes, and when a monitor turns off or comes back.
//!
//! Portable: it only uses [`DdcBus`], so it behaves the same on Windows (dxva2) and macOS (IOAVService).
//! A monitor is "off" when it left the bus or stopped answering for at least [`DeskConfig::off_after`]
//! and [`DeskConfig::min_misses`] scans in a row: one failed read, or the DP link re-training once
//! right after the monitor boots (seen on the 34", ~3 s gone), is never "off". A monitor that comes back is checked again (probe or
//! profile) before it can be written to.

use std::sync::Arc;
use std::time::Duration;

use crate::bus::{DdcBus, MonitorInfo};
use crate::clock::Clock;
use crate::edid::MonitorId;
use crate::error::DdcError;
use crate::monitor::{Capabilities, Monitor, Power, Status, SwitchResult};
use crate::profile::host_input;
use crate::protocol::{Input, Link};
use crate::{Opened, open};

/// How long a monitor found not compatible waits before it is checked again.
const INCOMPATIBLE_RETRY: Duration = Duration::from_secs(30);

/// Tuning for [`Desk`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeskConfig {
    /// How long a monitor must stay missing (not listed, or no reply) before it is reported off.
    pub off_after: Duration,
    /// And at least this many missed scans in a row.
    pub min_misses: u32,
    /// A monitor reported off that the OS still lists (standby) is probed at most this often. In
    /// standby the 34"'s PM core treats DDC traffic as a wake source; constant polling is the likely
    /// trigger of the hang seen on 2026-11-23 (docs/targets/lc34g55t/tandem-re.md, inferred).
    pub standby_probe_interval: Duration,
    /// How long after this host asked for a switch an input change still counts as this host's.
    pub own_switch_window: Duration,
}

impl Default for DeskConfig {
    fn default() -> Self {
        Self {
            off_after: Duration::from_secs(5),
            min_misses: 2,
            standby_probe_interval: Duration::from_secs(10),
            own_switch_window: Duration::from_secs(15),
        }
    }
}

/// Whether the monitor is reachable from this host right now.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Presence {
    /// Listed and answering.
    Present,
    /// Listed by the OS but not answering DDC/CI.
    Unreachable,
    /// Not listed by the OS (powered off, standby that drops the link, cable out).
    Absent,
}

/// What the desk knows about one monitor.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MonitorState {
    pub id: MonitorId,
    /// EDID name (for the UI).
    pub name: String,
    /// `"standard"` or a profile key once checked; `None` while not checked or not compatible (see
    /// [`Self::not_compatible`]). Only monitors with a kind are ever written to.
    pub kind: Option<&'static str>,
    /// Checked and found not compatible (listed, never written). False while it was never reachable.
    pub not_compatible: bool,
    pub presence: Presence,
    /// Reported off: absent or unreachable for `off_after` (and `min_misses` scans).
    pub off: bool,
    /// Last good status (kept while off, for context only).
    pub status: Option<Status>,
    /// The monitor input this host is plugged into (from the EDID product id), if the model is known.
    pub host_input: Option<Input>,
    pub capabilities: Option<Capabilities>,
}

impl MonitorState {
    /// Whether this host's picture is on this monitor. `Some(false)` when it is off or shows the other
    /// input; `None` when it cannot be known (unknown model, not compatible, input not read yet).
    pub fn shows_this_host(&self) -> Option<bool> {
        if self.off {
            return Some(false);
        }
        let input = self.status?.input?;
        Some(input == self.host_input?)
    }
}

/// A change found by [`Desk::scan`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeskEvent {
    /// First seen, or back after being off.
    Appeared { id: MonitorId },
    /// Left the bus or stopped answering (debounced).
    Off { id: MonitorId },
    /// The input on screen changed. `by_this_host` when it matches a switch this desk asked for;
    /// otherwise the OSD, the buttons or another host did it.
    InputChanged {
        id: MonitorId,
        old: Option<Input>,
        new: Option<Input>,
        by_this_host: bool,
    },
    /// Firmware power flag changed while answering (patched monitors only).
    PowerChanged { id: MonitorId, power: Power },
    /// Picture on the active input appeared or was lost (patched monitors only).
    SignalChanged { id: MonitorId, signal: bool },
}

struct Entry {
    id: MonitorId,
    name: String,
    host_input: Option<Input>,
    monitor: Option<Monitor>,
    /// Checked and found not compatible: not checked again before this time (the check reads the
    /// capabilities string, which can block for a minute while a monitor boots).
    incompatible_until: Option<Duration>,
    presence: Presence,
    off: bool,
    announced: bool,
    misses: u32,
    missing_since: Option<Duration>,
    /// While off and still listed: no DDC traffic before this time.
    quiet_until: Option<Duration>,
    status: Option<Status>,
    own_switch: Option<(Input, Duration)>,
}

impl Entry {
    fn state(&self) -> MonitorState {
        MonitorState {
            id: self.id.clone(),
            name: self.name.clone(),
            kind: self.monitor.as_ref().map(Monitor::kind),
            not_compatible: self.monitor.is_none() && self.incompatible_until.is_some(),
            presence: self.presence,
            off: self.off,
            status: self.status,
            host_input: self.host_input,
            capabilities: self.monitor.as_ref().map(Monitor::capabilities),
        }
    }
}

/// All monitors of this host.
pub struct Desk {
    bus: Arc<dyn DdcBus>,
    clock: Arc<dyn Clock>,
    config: DeskConfig,
    entries: Vec<Entry>,
}

impl Desk {
    pub fn new(bus: Arc<dyn DdcBus>, clock: Arc<dyn Clock>) -> Self {
        Self {
            bus,
            clock,
            config: DeskConfig::default(),
            entries: Vec::new(),
        }
    }

    pub fn with_config(mut self, config: DeskConfig) -> Self {
        self.config = config;
        self
    }

    /// Current knowledge, in the order monitors were first seen (off ones included).
    pub fn states(&self) -> Vec<MonitorState> {
        self.entries.iter().map(Entry::state).collect()
    }

    pub fn state(&self, id: &MonitorId) -> Option<MonitorState> {
        self.entries.iter().find(|e| &e.id == id).map(Entry::state)
    }

    /// Re-enumerates, reads every monitor once and returns what changed. Monitors without an EDID are
    /// ignored (no stable id).
    pub fn scan(&mut self) -> Result<Vec<DeskEvent>, DdcError> {
        let infos = self.bus.monitors()?;
        let mut events = Vec::new();
        let mut seen = vec![false; self.entries.len()];
        for info in &infos {
            let Some(id) = info.id() else { continue };
            let index = match self.entries.iter().position(|e| e.id == id) {
                Some(i) => i,
                None => {
                    self.entries.push(new_entry(id, info));
                    seen.push(false);
                    self.entries.len() - 1
                }
            };
            seen[index] = true;
            self.visit(index, info, &mut events);
        }
        for (index, was_seen) in seen.into_iter().enumerate() {
            if !was_seen {
                self.miss(index, Presence::Absent, &mut events);
            }
        }
        Ok(events)
    }

    /// Switches one monitor. The input change itself shows up in a later [`Self::scan`] as
    /// `InputChanged { by_this_host: true }`.
    pub fn switch(
        &mut self,
        id: &MonitorId,
        target: Input,
        timeout: Duration,
    ) -> Result<SwitchResult, DdcError> {
        let now = self.clock.now();
        let window = self.config.own_switch_window;
        let entry = self.controllable(id)?;
        entry.own_switch = Some((target, now + window + timeout));
        let monitor = entry.monitor.as_mut().ok_or_else(|| not_controllable(id))?;
        monitor.switch_input(target, timeout)
    }

    /// Puts one monitor in standby (see [`Monitor::power_off`]).
    pub fn power_off(&mut self, id: &MonitorId) -> Result<(), DdcError> {
        let entry = self.controllable(id)?;
        entry
            .monitor
            .as_ref()
            .ok_or_else(|| not_controllable(id))?
            .power_off()
    }

    /// Wakes one monitor by command (see [`Monitor::power_on`]: unsupported on every known model, and a
    /// monitor that is off has no channel to send it on).
    pub fn power_on(&mut self, id: &MonitorId) -> Result<(), DdcError> {
        let entry = self
            .entries
            .iter()
            .find(|e| &e.id == id)
            .ok_or_else(|| not_controllable(id))?;
        match &entry.monitor {
            Some(m) if !entry.off => m.power_on(),
            _ => Err(DdcError::Unsupported {
                code: crate::VCP_POWER,
            }),
        }
    }

    fn controllable(&mut self, id: &MonitorId) -> Result<&mut Entry, DdcError> {
        let entry = self
            .entries
            .iter_mut()
            .find(|e| &e.id == id)
            .ok_or_else(|| not_controllable(id))?;
        if entry.off || entry.presence != Presence::Present {
            return Err(DdcError::NoChannel(format!("monitor {id} is off")));
        }
        if entry.monitor.is_none() {
            return Err(not_controllable(id));
        }
        Ok(entry)
    }

    fn visit(&mut self, index: usize, info: &MonitorInfo, events: &mut Vec<DeskEvent>) {
        let link = Link::new(Arc::clone(&self.bus), Arc::clone(&self.clock), info.handle);
        let now = self.clock.now();
        let interval = self.config.standby_probe_interval;
        let entry = &mut self.entries[index];
        // Off but still listed (standby): stay quiet between probes, so DDC traffic does not keep
        // waking the monitor's PM core.
        if entry.off && entry.presence == Presence::Unreachable {
            if entry.quiet_until.is_some_and(|t| now < t) {
                self.miss(index, Presence::Unreachable, events);
                return;
            }
            entry.quiet_until = Some(now + interval);
        }
        // Known monitors are reattached to the new handle. One coming back from off is the same unit
        // (same EDID serial hash): a patched one is probed again (one Get, catches a firmware change),
        // a profiled one is not re-read (its capabilities read hangs while the G5 boots, 2026-11-23).
        let monitor = match (&entry.monitor, entry.off) {
            (Some(m), false) => Some(m.reattach(link)),
            (Some(Monitor::Profiled(m)), true) => Some(Monitor::Profiled(m.reattach(link))),
            (Some(Monitor::Standard(_)), true) => match link.clone().open_standard() {
                Ok(m) => Some(Monitor::Standard(m)),
                Err(DdcError::NotCompatible(_)) => match open(link, info) {
                    Opened::Standard(m) => Some(Monitor::Standard(m)),
                    Opened::Profiled(m) => Some(Monitor::Profiled(m)),
                    Opened::NotCompatible(_) | Opened::NoChannel(_) => None,
                },
                Err(_) => {
                    self.miss(index, Presence::Unreachable, events);
                    return;
                }
            },
            (None, _) if entry.incompatible_until.is_some_and(|t| now < t) => None,
            (None, _) => match open(link, info) {
                Opened::Standard(m) => Some(Monitor::Standard(m)),
                Opened::Profiled(m) => Some(Monitor::Profiled(m)),
                Opened::NotCompatible(_) => {
                    entry.incompatible_until = Some(now + INCOMPATIBLE_RETRY);
                    None
                }
                Opened::NoChannel(_) => {
                    self.miss(index, Presence::Unreachable, events);
                    return;
                }
            },
        };
        let entry = &mut self.entries[index];
        entry.monitor = monitor;
        let status = match &entry.monitor {
            Some(m) => match m.status() {
                Ok(s) => Some(s),
                Err(_) => {
                    self.miss(index, Presence::Unreachable, events);
                    return;
                }
            },
            None => None,
        };
        let now = self.clock.now();
        let entry = &mut self.entries[index];
        entry.misses = 0;
        entry.missing_since = None;
        entry.quiet_until = None;
        entry.presence = Presence::Present;
        if entry.off || !entry.announced {
            entry.off = false;
            entry.announced = true;
            events.push(DeskEvent::Appeared {
                id: entry.id.clone(),
            });
        } else if let (Some(before), Some(after)) = (entry.status, status) {
            if before.input != after.input {
                let by_this_host = entry
                    .own_switch
                    .is_some_and(|(target, until)| Some(target) == after.input && now <= until);
                if by_this_host {
                    entry.own_switch = None;
                }
                events.push(DeskEvent::InputChanged {
                    id: entry.id.clone(),
                    old: before.input,
                    new: after.input,
                    by_this_host,
                });
            }
            if before.power != after.power {
                events.push(DeskEvent::PowerChanged {
                    id: entry.id.clone(),
                    power: after.power,
                });
            }
            if let (Some(a), Some(b)) = (before.signal, after.signal)
                && a != b
            {
                events.push(DeskEvent::SignalChanged {
                    id: entry.id.clone(),
                    signal: b,
                });
            }
        }
        if status.is_some() {
            entry.status = status;
        }
    }

    fn miss(&mut self, index: usize, presence: Presence, events: &mut Vec<DeskEvent>) {
        let now = self.clock.now();
        let config = self.config;
        let entry = &mut self.entries[index];
        entry.presence = presence;
        entry.misses = entry.misses.saturating_add(1);
        let since = *entry.missing_since.get_or_insert(now);
        if !entry.off
            && entry.announced
            && entry.misses >= config.min_misses.max(1)
            && now.saturating_sub(since) >= config.off_after
        {
            entry.off = true;
            entry.own_switch = None;
            events.push(DeskEvent::Off {
                id: entry.id.clone(),
            });
        }
    }
}

fn new_entry(id: MonitorId, info: &MonitorInfo) -> Entry {
    Entry {
        id,
        name: info
            .edid
            .as_ref()
            .and_then(|e| e.name().map(str::to_owned))
            .unwrap_or_else(|| info.description.clone()),
        host_input: host_input(info),
        monitor: None,
        incompatible_until: None,
        presence: Presence::Absent,
        off: false,
        announced: false,
        misses: 0,
        missing_since: None,
        quiet_until: None,
        status: None,
        own_switch: None,
    }
}

fn not_controllable(id: &MonitorId) -> DdcError {
    DdcError::Protocol(format!("monitor {id} is not controllable"))
}
