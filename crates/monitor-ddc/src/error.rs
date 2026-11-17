use thiserror::Error;

use crate::bus::MonitorHandle;
use crate::protocol::Incompatibility;

/// Everything that can go wrong talking DDC/CI to a monitor.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum DdcError {
    /// The machine has no usable DDC channel (missing OS API, unsupported platform, link down).
    #[error("no DDC channel: {0}")]
    NoChannel(String),
    /// The handle does not belong to the last enumeration (the monitor went away or was re-enumerated).
    #[error("unknown monitor handle {0}")]
    UnknownMonitor(MonitorHandle),
    /// No valid reply (timeout, bad checksum, NACK). Usually transient: callers retry.
    #[error("no valid reply to VCP 0x{code:02x}")]
    NoReply { code: u8 },
    /// The monitor answered that it does not implement this code (MCCS result code 1).
    #[error("VCP 0x{code:02x} is not supported by the monitor")]
    Unsupported { code: u8 },
    /// The OS reported a failure for this request.
    #[error("bus error on VCP 0x{code:02x}: {detail}")]
    Bus { code: u8, detail: String },
    /// The read-only probe says the monitor does not speak the firmware protocol: it is never controlled.
    #[error("monitor is not compatible: {0}")]
    NotCompatible(Incompatibility),
    /// The monitor answered, but the answers break a protocol rule (for example an event that never validates).
    #[error("protocol error: {0}")]
    Protocol(String),
}

impl DdcError {
    /// Errors worth retrying: the request may succeed if sent again.
    pub fn is_transient(&self) -> bool {
        matches!(self, DdcError::NoReply { .. } | DdcError::Bus { .. })
    }
}
