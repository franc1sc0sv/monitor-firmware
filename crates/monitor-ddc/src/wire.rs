//! DDC/CI framing for backends that move raw I2C bytes (macOS IOAVService). Windows dxva2 does this
//! itself. Messages go to I2C address 0x37 with sub-address 0x51 (the host).

use crate::bus::VcpReply;
use crate::error::DdcError;

pub const DDC_ADDRESS: u8 = 0x37;
pub const HOST_ADDRESS: u8 = 0x51;
const DEST_WRITE: u8 = 0x6E;
const REPLY_SOURCE: u8 = 0x6E;
const REPLY_CHECKSUM_SEED: u8 = 0x50;
pub const CAPABILITIES_CODE: u8 = 0xF3;
const CAPABILITIES_REPLY: u8 = 0xE3;
/// Longest capabilities fragment reply: source, length, opcode, offset (2), 32 data bytes, checksum.
pub const CAPABILITIES_REPLY_LEN: usize = 38;
pub const VCP_REPLY_LEN: usize = 11;

/// Request bytes after the sub-address: length byte, payload, checksum.
pub fn encode(payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(payload.len() + 2);
    out.push(0x80 | (payload.len() as u8 & 0x7F));
    out.extend_from_slice(payload);
    let chk = out.iter().fold(DEST_WRITE ^ HOST_ADDRESS, |a, b| a ^ b);
    out.push(chk);
    out
}

pub fn get_vcp_request(code: u8) -> Vec<u8> {
    encode(&[0x01, code])
}

pub fn set_vcp_request(code: u8, value: u16) -> Vec<u8> {
    let [hi, lo] = value.to_be_bytes();
    encode(&[0x03, code, hi, lo])
}

pub fn capabilities_request(offset: u16) -> Vec<u8> {
    let [hi, lo] = offset.to_be_bytes();
    encode(&[CAPABILITIES_CODE, hi, lo])
}

/// Some paths return the reply without the source byte; put it back.
fn normalize(buf: &[u8]) -> Vec<u8> {
    if buf.first() == Some(&REPLY_SOURCE) {
        buf.to_vec()
    } else {
        let mut v = Vec::with_capacity(buf.len() + 1);
        v.push(REPLY_SOURCE);
        v.extend_from_slice(buf);
        v
    }
}

fn checksum_ok(frame: &[u8], chk: u8) -> bool {
    frame.iter().fold(REPLY_CHECKSUM_SEED, |a, b| a ^ b) == chk
}

/// Parses a Get VCP reply: `6E 88 02 rc code type MH ML CH CL chk`.
pub fn parse_vcp_reply(buf: &[u8], code: u8) -> Result<VcpReply, DdcError> {
    let r = normalize(buf);
    if r.len() < VCP_REPLY_LEN
        || r[1] != 0x88
        || r[2] != 0x02
        || r[4] != code
        || !checksum_ok(&r[..10], r[10])
    {
        return Err(DdcError::NoReply { code });
    }
    if r[3] != 0 {
        return Err(DdcError::Unsupported { code });
    }
    Ok(VcpReply::from_bytes(r[6], r[7], r[8], r[9]))
}

/// Parses one capabilities fragment (`6E 80|n E3 offH offL data.. chk`) and returns its data.
/// An empty fragment ends the string.
pub fn parse_capabilities_fragment(buf: &[u8], offset: u16) -> Result<Vec<u8>, DdcError> {
    let bad = DdcError::NoReply {
        code: CAPABILITIES_CODE,
    };
    let r = normalize(buf);
    if r.len() < 6 || r[1] & 0x80 == 0 {
        return Err(bad);
    }
    let len = usize::from(r[1] & 0x7F);
    if len < 3 || r.len() < len + 3 || r[2] != CAPABILITIES_REPLY {
        return Err(bad);
    }
    if !checksum_ok(&r[..len + 2], r[len + 2]) || u16::from_be_bytes([r[3], r[4]]) != offset {
        return Err(bad);
    }
    Ok(r[5..len + 2].to_vec())
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn reply(rc: u8, code: u8, data: [u8; 4]) -> Vec<u8> {
        let mut r = vec![
            0x6E, 0x88, 0x02, rc, code, 0x00, data[0], data[1], data[2], data[3],
        ];
        let chk = r.iter().fold(0x50, |a, b| a ^ b);
        r.push(chk);
        r
    }

    #[test]
    fn encodes_get_like_ddcutil() {
        // 0x6E ^ 0x51 ^ 0x82 ^ 0x01 ^ 0x10 = 0xAC (brightness request seen on the wire).
        assert_eq!(get_vcp_request(0x10), vec![0x82, 0x01, 0x10, 0xAC]);
    }

    #[test]
    fn unsupported_and_garbage_are_told_apart() {
        assert_eq!(
            parse_vcp_reply(&reply(1, 0xEA, [0; 4]), 0xEA),
            Err(DdcError::Unsupported { code: 0xEA })
        );
        let mut bad = reply(0, 0xEA, [1, 2, 3, 4]);
        bad[7] ^= 1;
        assert_eq!(
            parse_vcp_reply(&bad, 0xEA),
            Err(DdcError::NoReply { code: 0xEA })
        );
        assert_eq!(
            parse_vcp_reply(&reply(0, 0xEB, [0; 4]), 0xEA),
            Err(DdcError::NoReply { code: 0xEA })
        );
    }

    #[test]
    fn accepts_reply_without_source_byte() {
        let r = reply(0, 0x60, [0, 0x0E, 0, 0x09]);
        assert_eq!(
            parse_vcp_reply(&r[1..], 0x60),
            Ok(VcpReply {
                max: 0x0E,
                current: 0x09
            })
        );
    }

    #[test]
    fn parses_capabilities_fragments() {
        let data = b"(prot(monitor)";
        let mut r = vec![0x6E, 0x80 | (data.len() as u8 + 3), 0xE3, 0x00, 0x20];
        r.extend_from_slice(data);
        let chk = r.iter().fold(0x50, |a, b| a ^ b);
        r.push(chk);
        assert_eq!(parse_capabilities_fragment(&r, 0x20), Ok(data.to_vec()));
        assert!(parse_capabilities_fragment(&r, 0x00).is_err());
    }

    proptest! {
        #[test]
        fn vcp_reply_roundtrip(code in any::<u8>(), data in any::<[u8; 4]>()) {
            let parsed = parse_vcp_reply(&reply(0, code, data), code).unwrap();
            prop_assert_eq!(parsed, VcpReply::from_bytes(data[0], data[1], data[2], data[3]));
        }

        #[test]
        fn request_checksum_closes(payload in proptest::collection::vec(any::<u8>(), 0..32)) {
            let msg = encode(&payload);
            prop_assert_eq!(msg.iter().fold(0x6E ^ 0x51, |a, b| a ^ b), 0);
        }
    }
}
