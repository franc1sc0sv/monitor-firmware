//! DDC/CI control of monitors that run the patched firmware protocol (docs/protocol/vcp-interface.md).
//!
//! One standard only: a monitor is controlled if the read-only probe (Get 0xEA) confirms the firmware
//! protocol; otherwise it is listed as not compatible and never written to. Layers:
//!
//! - [`DdcBus`]: raw Get/Set VCP, capabilities and EDID per OS (Windows dxva2, macOS IOAVService),
//!   plus [`fake::FakeBus`] for tests.
//! - [`Link`]: retries and the probe; reads only.
//! - [`StandardMonitor`]: live state (0xEE), events with a cursor (0xEA-0xED), input switch with the
//!   firmware's verdict (Set 0x60 + `switch-done`/`switch-failed`).
//! - [`MonitorId`]: `<model>-<short hash of the EDID serial>`, the same on DP and HDMI.

mod bus;
mod clock;
mod edid;
mod error;
pub mod fake;
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
pub use edid::{Edid, EdidError, MonitorId};
pub use error::DdcError;
pub use protocol::{
    Event, EventBatch, EventCursor, EventKind, Incompatibility, Input, Link, LinkConfig, LiveState,
    MIN_PROTOCOL, Probe, RING_SIZE, RingInfo, StandardMonitor, VCP_CLOCK, VCP_CURSOR, VCP_INPUT,
    VCP_LIVE, VCP_RECORD, VCP_RECORD_TIME, VCP_RING, Verdict,
};

#[cfg(target_os = "macos")]
pub use mac::MacBus;
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
