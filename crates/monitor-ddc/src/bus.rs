use std::fmt;

use crate::edid::{Edid, MonitorId};
use crate::error::DdcError;

/// Opaque handle to a monitor from the last [`DdcBus::monitors`] call. Handles are not stable across
/// enumerations; [`MonitorId`] is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct MonitorHandle(pub u64);

impl fmt::Display for MonitorHandle {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "#{}", self.0)
    }
}

/// One monitor seen by a bus.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MonitorInfo {
    pub handle: MonitorHandle,
    /// What the OS calls it (for logs and the UI only).
    pub description: String,
    /// `None` when the OS did not give an EDID or it did not parse.
    pub edid: Option<Edid>,
}

impl MonitorInfo {
    pub fn id(&self) -> Option<MonitorId> {
        self.edid.as_ref().map(Edid::monitor_id)
    }
}

/// Reply to an MCCS Get VCP: the "maximum" field (MH ML) and the "current" field (CH CL).
/// The firmware protocol packs four independent bytes into these two fields.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct VcpReply {
    pub max: u16,
    pub current: u16,
}

impl VcpReply {
    pub fn from_bytes(mh: u8, ml: u8, ch: u8, cl: u8) -> Self {
        Self {
            max: u16::from_be_bytes([mh, ml]),
            current: u16::from_be_bytes([ch, cl]),
        }
    }

    pub fn mh(&self) -> u8 {
        self.max.to_be_bytes()[0]
    }

    pub fn ml(&self) -> u8 {
        self.max.to_be_bytes()[1]
    }

    pub fn ch(&self) -> u8 {
        self.current.to_be_bytes()[0]
    }

    pub fn cl(&self) -> u8 {
        self.current.to_be_bytes()[1]
    }
}

/// Raw DDC/CI access, one implementation per OS plus the [`crate::fake::FakeBus`] double.
///
/// Implementations do one attempt per call (no retries) and report MCCS "unsupported" as
/// [`DdcError::Unsupported`] so the protocol layer can tell it apart from a transient failure.
/// Everything above this trait is portable and tested on Linux.
pub trait DdcBus: Send + Sync {
    /// Re-enumerates the monitors. Handles from earlier calls may stop being valid.
    fn monitors(&self) -> Result<Vec<MonitorInfo>, DdcError>;
    fn get_vcp(&self, monitor: MonitorHandle, code: u8) -> Result<VcpReply, DdcError>;
    fn set_vcp(&self, monitor: MonitorHandle, code: u8, value: u16) -> Result<(), DdcError>;
    /// The MCCS capabilities string, e.g. `(prot(monitor)type(LCD)model(...)vcp(...))`.
    fn capabilities(&self, monitor: MonitorHandle) -> Result<String, DdcError>;
}
