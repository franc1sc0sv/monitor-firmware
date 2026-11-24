//! DDC/CI control of monitors that run the patched firmware protocol (docs/protocol/vcp-interface.md),
//! and of known stock models through data profiles (ADR-0020).
//!
//! A monitor is controlled only after a read-only check: the probe (Get 0xEA) confirms the firmware
//! protocol, or the EDID and capabilities match a built-in [`Profile`]. Anything else is listed as not
//! compatible and never written to. [`open`] runs both checks. Layers:
//!
//! - [`DdcBus`]: raw Get/Set VCP, capabilities and EDID per OS (Windows dxva2, macOS IOAVService),
//!   plus [`fake::FakeBus`] for tests.
//! - [`Link`]: retries and the probe; reads only.
//! - [`StandardMonitor`]: live state (0xEE), events with a cursor (0xEA-0xED), input switch with the
//!   firmware's verdict (Set 0x60 + `switch-done`/`switch-failed`).
//! - [`ProfiledMonitor`]: stock monitor of a known model; input by polling Get 0x60, switch with the
//!   profile's standard 0x60 values (no vendor codes).
//! - [`MonitorId`]: `<model>-<short hash of the EDID serial>`, the same on DP and HDMI.

mod bus;
mod clock;
mod desk;
mod edid;
mod error;
pub mod fake;
mod monitor;
mod profile;
mod protocol;
mod win_path;
pub mod wire;

#[cfg(target_os = "macos")]
mod mac;
#[cfg(windows)]
mod win;

use std::sync::Arc;

pub use bus::{DdcBus, MonitorHandle, MonitorInfo, VcpReply};
pub use clock::{Clock, SystemClock};
pub use desk::{Desk, DeskConfig, DeskEvent, MonitorState, Presence};
pub use edid::{Edid, EdidError, MonitorId};
pub use error::DdcError;
pub use monitor::{Capabilities, InputTruth, Monitor, Power, Status, SwitchProof, SwitchResult};
pub use profile::{
    HOST_PORTS, InputChange, PROFILES, PowerControl, Profile, ProfiledMonitor, ProfiledVerdict,
    VCP_POWER, caps_values, host_input, profile_for,
};
pub use protocol::{
    Event, EventBatch, EventCursor, EventKind, Incompatibility, Input, Link, LinkConfig, LiveState,
    MIN_PROTOCOL, Probe, RING_SIZE, RingInfo, StandardMonitor, VCP_CLOCK, VCP_CURSOR, VCP_INPUT,
    VCP_LIVE, VCP_RECORD, VCP_RECORD_TIME, VCP_RING, Verdict,
};

#[cfg(target_os = "macos")]
pub use mac::MacBus;

/// What a monitor turned out to be after the read-only checks.
pub enum Opened {
    /// Patched firmware (probe on 0xEA passed): events, live state, verdicts.
    Standard(StandardMonitor),
    /// Stock firmware of a known model (EDID + capabilities match a [`Profile`]): input by polling.
    Profiled(ProfiledMonitor),
    /// Answers, but neither: listed, never written to.
    NotCompatible(DdcError),
    /// No answer (powered off, standby, inactive input on the Mac).
    NoChannel(DdcError),
}

/// Opens a monitor the safe way: the firmware probe first, then the built-in profiles. Both checks
/// only read; a monitor that passes neither never receives a Set.
pub fn open(link: Link, info: &MonitorInfo) -> Opened {
    match link.clone().open_standard() {
        Ok(m) => Opened::Standard(m),
        Err(DdcError::NotCompatible(why)) => match link.open_profiled(info, PROFILES) {
            Ok(m) => Opened::Profiled(m),
            Err(e @ (DdcError::NoReply { .. } | DdcError::NoChannel(_))) => Opened::NoChannel(e),
            Err(_) => Opened::NotCompatible(DdcError::NotCompatible(why)),
        },
        Err(e) => Opened::NoChannel(e),
    }
}
#[cfg(windows)]
pub use win::WindowsBus;

/// The DDC bus of this machine. `Err(NoChannel)` when the platform has no backend or its OS API is
/// missing (for example IOAVService absent on this macOS); callers report that instead of failing.
pub fn system_bus() -> Result<Arc<dyn DdcBus>, DdcError> {
    #[cfg(windows)]
    {
        Ok(Arc::new(WindowsBus::new()))
    }
    #[cfg(target_os = "macos")]
    {
        Ok(Arc::new(MacBus::new()?))
    }
    #[cfg(not(any(windows, target_os = "macos")))]
    {
        Err(DdcError::NoChannel(
            "no DDC backend for this platform".into(),
        ))
    }
}
