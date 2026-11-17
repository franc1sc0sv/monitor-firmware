//! EDID parsing and the stable monitor identity.
//!
//! The serial number never leaves this module in clear: it is only hashed into [`MonitorId`], and the
//! `Debug` output of [`Edid`] leaves it out (repo rule: no serial numbers in logs, files or issues).

use std::fmt;

use sha2::{Digest, Sha256};
use thiserror::Error;

const HEADER: [u8; 8] = [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00];
const BLOCK: usize = 128;
const DESCRIPTORS: [usize; 4] = [54, 72, 90, 108];
const TAG_SERIAL: u8 = 0xFF;
const TAG_NAME: u8 = 0xFC;
/// Hex characters of the hash kept in the id (32 bits: enough to tell a desk's monitors apart).
const HASH_HEX_LEN: usize = 8;
const HASH_DOMAIN: &[u8] = b"monitor-ddc/id/v1:";

#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum EdidError {
    #[error("EDID shorter than one block ({0} bytes)")]
    TooShort(usize),
    #[error("missing EDID header")]
    BadHeader,
    #[error("EDID base block checksum mismatch")]
    BadChecksum,
}

/// The parts of an EDID this crate needs.
#[derive(Clone, PartialEq, Eq)]
pub struct Edid {
    raw: Vec<u8>,
    manufacturer: String,
    product: u16,
    name: Option<String>,
    serial_number: u32,
    serial_text: Option<String>,
}

impl Edid {
    pub fn parse(bytes: &[u8]) -> Result<Self, EdidError> {
        if bytes.len() < BLOCK {
            return Err(EdidError::TooShort(bytes.len()));
        }
        let base = &bytes[..BLOCK];
        if base[..8] != HEADER {
            return Err(EdidError::BadHeader);
        }
        if base.iter().fold(0u8, |a, b| a.wrapping_add(*b)) != 0 {
            return Err(EdidError::BadChecksum);
        }
        let packed = u16::from_be_bytes([base[8], base[9]]);
        let manufacturer = [10u16, 5, 0]
            .iter()
            .map(|shift| char::from(b'@' + ((packed >> shift) & 0x1F) as u8))
            .collect();
        let mut name = None;
        let mut serial_text = None;
        for &at in &DESCRIPTORS {
            let d = &base[at..at + 18];
            if d[..3] != [0, 0, 0] {
                continue;
            }
            match d[3] {
                TAG_NAME => name = descriptor_text(&d[5..]),
                TAG_SERIAL => serial_text = descriptor_text(&d[5..]),
                _ => {}
            }
        }
        Ok(Self {
            raw: bytes.to_vec(),
            manufacturer,
            product: u16::from_le_bytes([base[10], base[11]]),
            name,
            serial_number: u32::from_le_bytes([base[12], base[13], base[14], base[15]]),
            serial_text,
        })
    }

    /// Three-letter PNP id (`SAM` for Samsung).
    pub fn manufacturer(&self) -> &str {
        &self.manufacturer
    }

    /// Product code. Differs between the DP and the HDMI EDID of the same monitor.
    pub fn product(&self) -> u16 {
        self.product
    }

    /// Monitor name descriptor, e.g. `LC34G55T`.
    pub fn name(&self) -> Option<&str> {
        self.name.as_deref()
    }

    /// The full EDID as read. Contains the serial number: do not log or store it.
    pub fn raw(&self) -> &[u8] {
        &self.raw
    }

    /// `<model>-<short hash of the serial>`. The same for the DP and the HDMI EDID of one monitor,
    /// because neither the name nor the serial depend on the input (only the product code does).
    pub fn monitor_id(&self) -> MonitorId {
        let model = match &self.name {
            Some(n) if !slug(n).is_empty() => slug(n),
            // Not the product code: it changes with the input and would split DP from HDMI.
            _ => self.manufacturer.to_ascii_lowercase(),
        };
        // Without any serial, the hash is of an empty string: still a valid id, unique per model only.
        let serial: Vec<u8> = match (&self.serial_text, self.serial_number) {
            (Some(text), _) => text.as_bytes().to_vec(),
            (None, n) if n != 0 => n.to_le_bytes().to_vec(),
            _ => Vec::new(),
        };
        let digest = Sha256::new()
            .chain_update(HASH_DOMAIN)
            .chain_update(&serial)
            .finalize();
        let hash: String = digest.iter().map(|b| format!("{b:02x}")).collect();
        MonitorId(format!("{model}-{}", &hash[..HASH_HEX_LEN]))
    }
}

impl fmt::Debug for Edid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Edid")
            .field("manufacturer", &self.manufacturer)
            .field("product", &format_args!("0x{:04x}", self.product))
            .field("name", &self.name)
            .field("id", &self.monitor_id())
            .finish_non_exhaustive()
    }
}

/// Stable identity of a physical monitor, safe to log and store.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct MonitorId(String);

impl MonitorId {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for MonitorId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

fn descriptor_text(bytes: &[u8]) -> Option<String> {
    let end = bytes.iter().position(|b| *b == 0x0A).unwrap_or(bytes.len());
    let text: String = bytes[..end].iter().map(|b| char::from(*b)).collect();
    let text = text.trim().to_string();
    (!text.is_empty()).then_some(text)
}

fn slug(name: &str) -> String {
    let mut out = String::new();
    for c in name.chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c.to_ascii_lowercase());
        } else if !out.is_empty() && !out.ends_with('-') {
            out.push('-');
        }
    }
    out.trim_end_matches('-').to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fake::test_edid;
    use proptest::prelude::*;

    #[test]
    fn parses_identity_fields() {
        let e = Edid::parse(&test_edid("SAM", 0x7155, "LC34G55T", "TESTSERIAL01")).unwrap();
        assert_eq!(e.manufacturer(), "SAM");
        assert_eq!(e.product(), 0x7155);
        assert_eq!(e.name(), Some("LC34G55T"));
        assert!(e.monitor_id().as_str().starts_with("lc34g55t-"));
        assert_eq!(
            e.monitor_id().as_str().len(),
            "lc34g55t-".len() + HASH_HEX_LEN
        );
    }

    #[test]
    fn rejects_bad_edids() {
        let mut e = test_edid("SAM", 1, "X", "Y");
        assert_eq!(Edid::parse(&e[..100]), Err(EdidError::TooShort(100)));
        e[127] = e[127].wrapping_add(1);
        assert_eq!(Edid::parse(&e), Err(EdidError::BadChecksum));
        e[0] = 1;
        assert_eq!(Edid::parse(&e), Err(EdidError::BadHeader));
    }

    #[test]
    fn debug_never_shows_the_serial() {
        let e = Edid::parse(&test_edid("SAM", 1, "LC34G55T", "SECRETSERIAL")).unwrap();
        assert!(!format!("{e:?}").contains("SECRETSERIAL"));
    }

    #[test]
    fn falls_back_to_the_manufacturer_without_a_name() {
        let e = Edid::parse(&test_edid("DEL", 0x40ab, "", "S1")).unwrap();
        assert!(e.monitor_id().as_str().starts_with("del-"));
    }

    proptest! {
        #[test]
        fn dp_and_hdmi_edids_share_the_id(
            name in "[A-Za-z0-9 ]{1,13}",
            serial in "[A-Z0-9]{4,13}",
            dp in any::<u16>(),
            hdmi in any::<u16>(),
        ) {
            let a = Edid::parse(&test_edid("SAM", dp, &name, &serial)).unwrap();
            let b = Edid::parse(&test_edid("SAM", hdmi, &name, &serial)).unwrap();
            prop_assert_eq!(a.monitor_id(), b.monitor_id());
            prop_assert!(!a.monitor_id().as_str().contains(&serial));
        }

        #[test]
        fn different_serials_give_different_ids(s1 in "[A-Z0-9]{8,13}", s2 in "[A-Z0-9]{8,13}") {
            prop_assume!(s1 != s2);
            let a = Edid::parse(&test_edid("SAM", 1, "M", &s1)).unwrap();
            let b = Edid::parse(&test_edid("SAM", 1, "M", &s2)).unwrap();
            // 32-bit hash: a collision here would be a 1-in-4-billion event per case.
            prop_assert_ne!(a.monitor_id(), b.monitor_id());
        }
    }
}
