//! One API for every controllable monitor, whatever its firmware.
//!
//! [`Monitor`] wraps a patched monitor ([`StandardMonitor`]) or a profiled stock one
//! ([`ProfiledMonitor`]) behind the same essentials: status (input, power, signal), input switch with a
//! result, and power commands. What a model cannot do is stated by [`Capabilities`] and answered with
//! [`DdcError::Unsupported`], never faked.

use std::time::Duration;

use crate::bus::MonitorHandle;
use crate::error::DdcError;
use crate::profile::{PowerControl, ProfiledMonitor, ProfiledVerdict, VCP_POWER};
use crate::protocol::{Input, Link, StandardMonitor, Verdict};

/// Where the reported input comes from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputTruth {
    /// The patched firmware reports the input on screen and logs every change.
    Firmware,
    /// The stock firmware reports the input on screen; changes are found by polling.
    Polled,
}

/// What a switch result proves.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SwitchProof {
    /// The firmware saw a locked picture on the target (or none: failed).
    Picture,
    /// The monitor reports the target; the picture is not checked.
    Accepted,
}

/// What this monitor can do, per model and firmware (measured on hardware, see `docs/targets/`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Capabilities {
    pub input_truth: InputTruth,
    pub switch_proof: SwitchProof,
    /// Reports whether the active input has a picture.
    pub signal: bool,
    /// Can be put in standby by command.
    pub power_off: bool,
    /// Can be woken by command over DDC. False on both supported models: the 34" drops its DP link in
    /// standby and the G5 ignores 0xD6 (confirmed 2026-11-23).
    pub power_on: bool,
}

/// Power as the monitor itself reports it while it answers. A monitor that stopped answering or left
/// the bus is tracked by [`crate::Desk`] as off.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Power {
    On,
    /// The firmware reports power off/standby while still answering DDC.
    Standby,
}

/// One status read.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Status {
    /// Input on screen; `None` for a value the model does not map.
    pub input: Option<Input>,
    pub power: Power,
    /// Picture on the active input; `None` when the model cannot tell.
    pub signal: Option<bool>,
}

/// Result of an input switch, the same for every model.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SwitchResult {
    /// The firmware confirmed a locked picture on the target.
    Confirmed { input: Input },
    /// The monitor reports the target (stock firmware: picture not checked, usually 1-2 s later).
    Accepted { input: Input },
    /// The monitor did not end on the target; `current` is what it shows.
    Failed {
        target: Input,
        current: Option<Input>,
    },
    /// No answer or no verdict before the deadline.
    TimedOut,
}

impl SwitchResult {
    /// True when the monitor ended on the target.
    pub fn succeeded(&self) -> bool {
        matches!(
            self,
            SwitchResult::Confirmed { .. } | SwitchResult::Accepted { .. }
        )
    }
}

/// A controllable monitor.
#[derive(Clone)]
pub enum Monitor {
    Standard(StandardMonitor),
    Profiled(ProfiledMonitor),
}

impl Monitor {
    pub fn handle(&self) -> MonitorHandle {
        match self {
            Monitor::Standard(m) => m.handle(),
            Monitor::Profiled(m) => m.handle(),
        }
    }

    /// `"standard"` or the profile key (e.g. `"g5-falcon"`).
    pub fn kind(&self) -> &'static str {
        match self {
            Monitor::Standard(_) => "standard",
            Monitor::Profiled(m) => m.profile().key,
        }
    }

    pub fn capabilities(&self) -> Capabilities {
        match self {
            Monitor::Standard(_) => Capabilities {
                input_truth: InputTruth::Firmware,
                switch_proof: SwitchProof::Picture,
                signal: true,
                power_off: true,
                power_on: false,
            },
            Monitor::Profiled(m) => Capabilities {
                input_truth: InputTruth::Polled,
                switch_proof: SwitchProof::Accepted,
                signal: false,
                power_off: m.profile().power != PowerControl::None,
                power_on: false,
            },
        }
    }

    /// One status read (one Get on either kind: 0xEE or 0x60).
    pub fn status(&self) -> Result<Status, DdcError> {
        match self {
            Monitor::Standard(m) => {
                let live = m.live()?;
                Ok(Status {
                    input: live.input(),
                    power: if live.power_on() {
                        Power::On
                    } else {
                        Power::Standby
                    },
                    signal: Some(live.signal),
                })
            }
            Monitor::Profiled(m) => Ok(Status {
                input: m.input()?,
                power: Power::On,
                signal: None,
            }),
        }
    }

    /// Switches the input and waits for the result.
    pub fn switch_input(
        &mut self,
        target: Input,
        timeout: Duration,
    ) -> Result<SwitchResult, DdcError> {
        match self {
            Monitor::Standard(m) => Ok(match m.switch_input(target, timeout)? {
                Verdict::Confirmed { .. } => SwitchResult::Confirmed { input: target },
                Verdict::Failed { current, .. } => SwitchResult::Failed { target, current },
                Verdict::TimedOut => SwitchResult::TimedOut,
            }),
            Monitor::Profiled(m) => Ok(match m.switch_input(target, timeout)? {
                ProfiledVerdict::Accepted { input } => SwitchResult::Accepted { input },
                ProfiledVerdict::NotAccepted { current } => {
                    SwitchResult::Failed { target, current }
                }
                ProfiledVerdict::TimedOut => SwitchResult::TimedOut,
            }),
        }
    }

    /// Puts the monitor in standby (MCCS 0xD6 = 4). On the 34" this also drops its DP link, so it cannot
    /// be woken by command from a DP host afterwards. `Unsupported` where the model ignores 0xD6.
    pub fn power_off(&self) -> Result<(), DdcError> {
        if !self.capabilities().power_off {
            return Err(DdcError::Unsupported { code: VCP_POWER });
        }
        match self {
            Monitor::Standard(m) => m.set_vcp(VCP_POWER, 4),
            Monitor::Profiled(_) => Err(DdcError::Unsupported { code: VCP_POWER }),
        }
    }

    /// Wakes the monitor by command. No supported model can (see [`Capabilities::power_on`]): always
    /// `Unsupported` today, so callers fall back to waking by video signal or the power button.
    pub fn power_on(&self) -> Result<(), DdcError> {
        Err(DdcError::Unsupported { code: VCP_POWER })
    }

    /// Same monitor on a handle from a newer enumeration (checks are not repeated).
    pub(crate) fn reattach(&self, link: Link) -> Self {
        match self {
            Monitor::Standard(m) => Monitor::Standard(m.reattach(link)),
            Monitor::Profiled(m) => Monitor::Profiled(m.reattach(link)),
        }
    }
}
