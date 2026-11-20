//! DDC/CI requests over a raw I2C transport (write the request, wait, read the reply), shared by the
//! backends that move raw bytes (macOS IOAVService). Kept apart from the FFI so the retry and the
//! timing are tested on Linux with a double.

use std::time::Duration;

use crate::bus::VcpReply;
use crate::clock::Clock;
use crate::error::DdcError;
use crate::wire;

/// Request to reply: DDC/CI asks the host to wait at least 40 ms (MCCS 50-150 ms for most commands).
/// 50 ms is what the 2026-11-20 inactive-HDMI experiment used and what answered on the first try.
pub const REPLY_WAIT: Duration = Duration::from_millis(50);
/// The Apple DCP drops a write now and then (the call fails); one more try fixes it.
pub const WRITE_TRIES: usize = 2;
/// Pause before the second write, so the DCP is not hit again in the same instant.
pub const WRITE_RETRY_DELAY: Duration = Duration::from_millis(10);
/// Upper bound for a capabilities string, in fragments (each up to 32 bytes).
pub const MAX_FRAGMENTS: usize = 256;

/// One raw I2C exchange with the monitor's DDC/CI address, as the OS exposes it. Each call is one
/// attempt; `false` means the OS reported a failure.
pub trait RawI2c {
    fn write(&mut self, msg: &[u8]) -> bool;
    fn read(&mut self, buf: &mut [u8]) -> bool;
}

fn write(io: &mut impl RawI2c, clock: &dyn Clock, msg: &[u8], code: u8) -> Result<(), DdcError> {
    for attempt in 0..WRITE_TRIES {
        if attempt > 0 {
            clock.sleep(WRITE_RETRY_DELAY);
        }
        if io.write(msg) {
            return Ok(());
        }
    }
    Err(DdcError::Bus {
        code,
        detail: "I2C write failed".into(),
    })
}

fn read(io: &mut impl RawI2c, len: usize, code: u8) -> Result<Vec<u8>, DdcError> {
    let mut buf = vec![0u8; len];
    if !io.read(&mut buf) {
        return Err(DdcError::NoReply { code });
    }
    Ok(buf)
}

/// Get VCP: write, wait [`REPLY_WAIT`], read and check the reply (a stale reply to another code is
/// `NoReply`, which the [`crate::Link`] retries).
pub fn get_vcp(io: &mut impl RawI2c, clock: &dyn Clock, code: u8) -> Result<VcpReply, DdcError> {
    write(io, clock, &wire::get_vcp_request(code), code)?;
    clock.sleep(REPLY_WAIT);
    let buf = read(io, wire::VCP_REPLY_LEN + 1, code)?;
    wire::parse_vcp_reply(&buf, code)
}

/// Set VCP: write and give the monitor the same time before the next request.
pub fn set_vcp(
    io: &mut impl RawI2c,
    clock: &dyn Clock,
    code: u8,
    value: u16,
) -> Result<(), DdcError> {
    write(io, clock, &wire::set_vcp_request(code, value), code)?;
    clock.sleep(REPLY_WAIT);
    Ok(())
}

/// The capabilities string, fragment by fragment, each with its own write, wait and read.
pub fn capabilities(io: &mut impl RawI2c, clock: &dyn Clock) -> Result<String, DdcError> {
    let code = wire::CAPABILITIES_CODE;
    let mut out = Vec::new();
    for _ in 0..MAX_FRAGMENTS {
        let offset = u16::try_from(out.len())
            .map_err(|_| DdcError::Protocol("capabilities too long".into()))?;
        write(io, clock, &wire::capabilities_request(offset), code)?;
        clock.sleep(REPLY_WAIT);
        let buf = read(io, wire::CAPABILITIES_REPLY_LEN, code)?;
        let chunk = wire::parse_capabilities_fragment(&buf, offset)?;
        if chunk.is_empty() {
            break;
        }
        out.extend_from_slice(&chunk);
    }
    let end = out.iter().position(|b| *b == 0).unwrap_or(out.len());
    Ok(String::from_utf8_lossy(&out[..end]).into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fake::FakeClock;
    use std::collections::VecDeque;

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum Op {
        Write { at: Duration, ok: bool },
        Read { at: Duration },
    }

    /// I2C double: fails the first `drop_writes` writes, answers reads from a queue and records the
    /// time of every call on the shared fake clock.
    struct FakeI2c {
        clock: FakeClock,
        drop_writes: usize,
        replies: VecDeque<Vec<u8>>,
        ops: Vec<Op>,
    }

    impl FakeI2c {
        fn new(clock: &FakeClock, drop_writes: usize, replies: Vec<Vec<u8>>) -> Self {
            Self {
                clock: clock.clone(),
                drop_writes,
                replies: replies.into(),
                ops: Vec::new(),
            }
        }

        fn last_write_to_read(&self) -> Vec<Duration> {
            let mut gaps = Vec::new();
            let mut last = None;
            for op in &self.ops {
                match op {
                    Op::Write { at, ok: true } => last = Some(*at),
                    Op::Write { ok: false, .. } => {}
                    Op::Read { at } => {
                        if let Some(w) = last.take() {
                            gaps.push(*at - w);
                        }
                    }
                }
            }
            gaps
        }
    }

    impl RawI2c for FakeI2c {
        fn write(&mut self, _msg: &[u8]) -> bool {
            let ok = self.drop_writes == 0;
            self.drop_writes = self.drop_writes.saturating_sub(1);
            self.ops.push(Op::Write {
                at: self.clock.now(),
                ok,
            });
            ok
        }

        fn read(&mut self, buf: &mut [u8]) -> bool {
            self.ops.push(Op::Read {
                at: self.clock.now(),
            });
            match self.replies.pop_front() {
                Some(r) => {
                    let n = r.len().min(buf.len());
                    buf[..n].copy_from_slice(&r[..n]);
                    true
                }
                None => false,
            }
        }
    }

    fn reply(code: u8, data: [u8; 4]) -> Vec<u8> {
        let mut r = vec![
            0x6E, 0x88, 0x02, 0x00, code, 0x00, data[0], data[1], data[2], data[3],
        ];
        let chk = r.iter().fold(0x50, |a, b| a ^ b);
        r.push(chk);
        r
    }

    /// The probe reply the 34" gave on its inactive HDMI input on 2026-11-20.
    fn probe_reply() -> Vec<u8> {
        reply(0xEA, [0x00, 0x40, 0x02, 0x00])
    }

    #[test]
    fn a_dropped_first_write_is_sent_again() {
        let clock = FakeClock::new();
        let mut io = FakeI2c::new(&clock, 1, vec![probe_reply()]);
        let got = get_vcp(&mut io, &clock, 0xEA);
        assert_eq!(got, Ok(VcpReply::from_bytes(0x00, 0x40, 0x02, 0x00)));
        let writes = io
            .ops
            .iter()
            .filter(|o| matches!(o, Op::Write { .. }))
            .count();
        assert_eq!(writes, 2, "one retry, no more");
    }

    #[test]
    fn two_dropped_writes_are_a_bus_error_and_nothing_is_read() {
        let clock = FakeClock::new();
        let mut io = FakeI2c::new(&clock, 2, vec![probe_reply()]);
        let got = get_vcp(&mut io, &clock, 0xEA);
        assert!(matches!(got, Err(DdcError::Bus { code: 0xEA, .. })));
        assert!(got.is_err_and(|e| e.is_transient()), "the Link retries it");
        assert!(!io.ops.iter().any(|o| matches!(o, Op::Read { .. })));
    }

    #[test]
    fn the_read_waits_the_reply_delay_after_the_write() {
        let clock = FakeClock::new();
        for drops in 0..WRITE_TRIES {
            let mut io = FakeI2c::new(&clock, drops, vec![probe_reply()]);
            get_vcp(&mut io, &clock, 0xEA).expect("reply");
            let gaps = io.last_write_to_read();
            assert_eq!(gaps.len(), 1);
            assert!(gaps[0] >= Duration::from_millis(40), "{gaps:?}");
        }
    }

    #[test]
    fn a_stale_reply_to_another_code_is_no_reply() {
        let clock = FakeClock::new();
        let mut io = FakeI2c::new(&clock, 0, vec![reply(0x10, [0, 100, 0, 99])]);
        assert_eq!(
            get_vcp(&mut io, &clock, 0xEA),
            Err(DdcError::NoReply { code: 0xEA })
        );
    }

    #[test]
    fn a_failed_read_is_no_reply() {
        let clock = FakeClock::new();
        let mut io = FakeI2c::new(&clock, 0, Vec::new());
        assert_eq!(
            get_vcp(&mut io, &clock, 0x60),
            Err(DdcError::NoReply { code: 0x60 })
        );
    }

    #[test]
    fn a_set_waits_before_the_next_request() {
        let clock = FakeClock::new();
        let mut io = FakeI2c::new(&clock, 1, Vec::new());
        set_vcp(&mut io, &clock, 0x60, 0x0F).expect("written");
        assert!(clock.now() >= WRITE_RETRY_DELAY + REPLY_WAIT);
    }

    fn fragment(offset: u16, data: &[u8]) -> Vec<u8> {
        let [hi, lo] = offset.to_be_bytes();
        let mut r = vec![0x6E, 0x80 | (data.len() as u8 + 3), 0xE3, hi, lo];
        r.extend_from_slice(data);
        let chk = r.iter().fold(0x50, |a, b| a ^ b);
        r.push(chk);
        r
    }

    #[test]
    fn capabilities_wait_before_every_fragment() {
        let clock = FakeClock::new();
        let mut io = FakeI2c::new(
            &clock,
            1,
            vec![
                fragment(0, b"(prot"),
                fragment(5, b"(x))"),
                fragment(9, b""),
            ],
        );
        assert_eq!(capabilities(&mut io, &clock), Ok("(prot(x))".into()));
        let gaps = io.last_write_to_read();
        assert_eq!(gaps.len(), 3);
        assert!(gaps.iter().all(|g| *g >= Duration::from_millis(40)));
    }
}
