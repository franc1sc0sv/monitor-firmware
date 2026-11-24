//! Known stock monitors that can be controlled without the patched firmware (ADR-0020).
//!
//! A stock monitor is only written to when **all** of these match, checked with reads only:
//! the EDID manufacturer and product id are in a [`Profile`], the MCCS capabilities string names the
//! profile's model token, and it lists both input values of the profile under VCP 0x60. Then only the
//! standard MCCS codes the profile allows are ever sent (no vendor codes: the G5 dev images give
//! 0xF0..0xF8 dangerous meanings).
//!
//! Profiles are data: a repaired or new monitor of a known model needs no code change.

use std::time::Duration;

use crate::bus::{MonitorHandle, MonitorInfo};
use crate::error::DdcError;
use crate::protocol::{CapabilityWord, Input, Link, VCP_INPUT};

/// MCCS power mode (VCP 0xD6).
pub const VCP_POWER: u8 = 0xD6;

/// What the monitor does with VCP 0xD6, measured on hardware.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PowerControl {
    /// The monitor ignores 0xD6 (no effect for 1, 4 or 5).
    None,
    /// 0xD6 = 4 puts it in standby, but the DisplayPort link drops with it, so the host loses the monitor
    /// and cannot send 0xD6 = 1: waking needs a video signal or the power button.
    OffOnly,
}

/// One supported stock model. Values are the ones confirmed on hardware (see `docs/targets/`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Profile {
    /// Short stable name, used in monitor ids and logs.
    pub key: &'static str,
    pub name: &'static str,
    /// EDID manufacturer (three letters).
    pub manufacturer: &'static str,
    /// EDID product ids (one per input: the monitor reports a different id on DP and on HDMI).
    pub products: &'static [u16],
    /// Text that must appear in the capabilities string (for example `model(LEMON23)`).
    pub caps_token: &'static str,
    /// Set/Get 0x60 value for DisplayPort.
    pub dp: u16,
    /// Set/Get 0x60 value for HDMI.
    pub hdmi: u16,
    pub power: PowerControl,
    /// Protocol 3 capability bits this model's patched firmware announces but does not deliver.
    pub patched_ignored_caps: u16,
}

impl Profile {
    pub fn vcp(&self, input: Input) -> u16 {
        match input {
            Input::DisplayPort => self.dp,
            Input::Hdmi => self.hdmi,
        }
    }

    pub fn input_from_vcp(&self, value: u16) -> Option<Input> {
        let v = value & 0xFF;
        if v == self.dp {
            Some(Input::DisplayPort)
        } else if v == self.hdmi {
            Some(Input::Hdmi)
        } else {
            None
        }
    }

    fn matches_edid(&self, info: &MonitorInfo) -> bool {
        info.edid.as_ref().is_some_and(|e| {
            e.manufacturer() == self.manufacturer && self.products.contains(&e.product())
        })
    }

    /// True when the capabilities string names this model and lists both input values under 0x60.
    pub fn matches_capabilities(&self, caps: &str) -> bool {
        if !caps.contains(self.caps_token) {
            return false;
        }
        let Some(values) = caps_values(caps, VCP_INPUT) else {
            return false;
        };
        values.contains(&self.dp) && values.contains(&self.hdmi)
    }
}

/// Built-in profiles.
///
/// The 32" Odyssey G5 "FALCON" (Novatek): stock firmware, confirmed 2026-11-23 from a Windows PC over
/// DisplayPort: capabilities `model(LEMON23)` with `60(11 0F)`; Set 0x60 = 0x0F shows DP and 0x11 shows
/// HDMI; Get 0x60 reports the input on screen (0x11 while the Mac on HDMI was shown, queried over DP);
/// 0xD6 = 1, 4 and 5 have no effect.
pub const PROFILES: &[Profile] = &[Profile {
    key: "g5-falcon",
    name: "Odyssey G5 32 (FALCON)",
    manufacturer: "SAM",
    products: &[0x7489, 0x748A],
    caps_token: "model(LEMON23)",
    dp: 0x0F,
    hdmi: 0x11,
    power: PowerControl::None,
    // Production image p3d (1033.0), measured 2026-11-24: the cable state of the input not on screen never
    // changes (HDMI unplugged for 20 s while DP was shown: 0xE8 MH stayed 3), so the switch guard cannot
    // refuse a switch to an unplugged HDMI.
    patched_ignored_caps: CapabilityWord::CABLE_DETECT | CapabilityWord::SWITCH_GUARD,
}];

/// Which input of the monitor a host is plugged into, from the EDID product id the host reads (the
/// monitors report a different id per input). Data, per model:
/// - LC34G55T: `0x711A` on DP (confirmed 2026-11-23 from the PC), `0x7119` on HDMI (inferred: listed by
///   the PC's display history from the AMD HDMI lab link).
/// - Odyssey G5: `0x7489` on DP, `0x748A` on HDMI (confirmed).
pub const HOST_PORTS: &[(&str, u16, Input)] = &[
    ("SAM", 0x711A, Input::DisplayPort),
    ("SAM", 0x7119, Input::Hdmi),
    ("SAM", 0x7489, Input::DisplayPort),
    ("SAM", 0x748A, Input::Hdmi),
];

/// The monitor input this host is plugged into, if the model is known.
pub fn host_input(info: &MonitorInfo) -> Option<Input> {
    let edid = info.edid.as_ref()?;
    HOST_PORTS
        .iter()
        .find(|(m, p, _)| *m == edid.manufacturer() && *p == edid.product())
        .map(|(_, _, input)| *input)
}

/// The profile whose EDID identity matches, if any (no bus traffic).
pub fn profile_for(info: &MonitorInfo, profiles: &'static [Profile]) -> Option<&'static Profile> {
    profiles.iter().find(|p| p.matches_edid(info))
}

/// The value list of `code` in an MCCS capabilities string, e.g. `60(11 0F)` → `[0x11, 0x0F]`.
/// `None` when the code is absent or has no value list.
pub fn caps_values(caps: &str, code: u8) -> Option<Vec<u16>> {
    let lower = caps.to_ascii_lowercase();
    let start = lower.find("vcp(")? + 4;
    let bytes = lower.as_bytes();
    let wanted = format!("{code:02x}");
    let mut i = start;
    let mut depth = 0usize;
    while i < bytes.len() {
        match bytes[i] {
            b'(' => depth += 1,
            b')' if depth == 0 => return None,
            b')' => depth -= 1,
            c if depth == 0 && c.is_ascii_hexdigit() => {
                let end = (i..bytes.len())
                    .find(|&j| !bytes[j].is_ascii_hexdigit())
                    .unwrap_or(bytes.len());
                if lower[i..end] == wanted {
                    let rest = lower[end..].trim_start();
                    let list = rest.strip_prefix('(')?;
                    let close = list.find(')')?;
                    return Some(
                        list[..close]
                            .split_whitespace()
                            .filter_map(|v| u16::from_str_radix(v, 16).ok())
                            .collect(),
                    );
                }
                i = end;
                continue;
            }
            _ => {}
        }
        i += 1;
    }
    None
}

/// How a profiled monitor's switch ended. A stock monitor has no "picture locked" signal: the best it
/// gives is that Get 0x60 now reports the target.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProfiledVerdict {
    /// Get 0x60 reports the target (the monitor took the request; the picture may need 1-2 s more).
    Accepted { input: Input },
    /// Still on another input at the deadline.
    NotAccepted { current: Option<Input> },
    /// No reply at all until the deadline.
    TimedOut,
}

/// A change seen by polling a profiled monitor (the stock firmware has no event ring).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InputChange {
    pub old: Option<Input>,
    pub new: Option<Input>,
}

/// A stock monitor that matched a profile. Only standard MCCS codes are sent.
#[derive(Clone)]
pub struct ProfiledMonitor {
    link: Link,
    profile: &'static Profile,
    last: Option<Option<Input>>,
}

impl ProfiledMonitor {
    /// Same monitor (same [`crate::MonitorId`]) on a handle from a newer enumeration, already checked.
    pub(crate) fn reattach(&self, link: Link) -> Self {
        Self {
            link,
            profile: self.profile,
            last: self.last,
        }
    }

    pub fn handle(&self) -> MonitorHandle {
        self.link.handle()
    }

    pub fn profile(&self) -> &'static Profile {
        self.profile
    }

    /// Get 0x60, decoded with the profile. `None` for a value the profile does not know.
    pub fn input(&self) -> Result<Option<Input>, DdcError> {
        Ok(self
            .profile
            .input_from_vcp(self.link.get(VCP_INPUT)?.current))
    }

    /// Polls the input once; returns the change since the previous call (the first call only records).
    pub fn poll(&mut self) -> Result<Option<InputChange>, DdcError> {
        let now = self.input()?;
        let change = match self.last {
            Some(before) if before != now => Some(InputChange {
                old: before,
                new: now,
            }),
            _ => None,
        };
        self.last = Some(now);
        Ok(change)
    }

    /// Set 0x60 with the profile's value, then poll Get 0x60 until it reports the target.
    pub fn switch_input(
        &mut self,
        target: Input,
        timeout: Duration,
    ) -> Result<ProfiledVerdict, DdcError> {
        let clock = self.link.clock();
        let value = self.profile.vcp(target);
        self.link.set_checked(VCP_INPUT, value)?;
        let deadline = clock.now() + timeout;
        let mut current = None;
        let mut answered = false;
        while clock.now() < deadline {
            clock.sleep(self.link.config().poll_interval);
            let Ok(reply) = self.link.get(VCP_INPUT) else {
                continue;
            };
            answered = true;
            current = self.profile.input_from_vcp(reply.current);
            if current == Some(target) {
                self.last = Some(current);
                return Ok(ProfiledVerdict::Accepted { input: target });
            }
        }
        Ok(if answered {
            ProfiledVerdict::NotAccepted { current }
        } else {
            ProfiledVerdict::TimedOut
        })
    }
}

impl Link {
    /// Read-only check against `profiles`: EDID identity, then the capabilities string. Only a full
    /// match returns a monitor that can be written to.
    pub fn open_profiled(
        self,
        info: &MonitorInfo,
        profiles: &'static [Profile],
    ) -> Result<ProfiledMonitor, DdcError> {
        let not_known =
            || DdcError::Protocol(format!("monitor {} matches no profile", info.handle));
        let profile = profile_for(info, profiles).ok_or_else(not_known)?;
        let caps = self.capabilities_once()?;
        if !profile.matches_capabilities(&caps) {
            return Err(DdcError::Protocol(format!(
                "monitor {} has the EDID of {} but its capabilities do not match",
                info.handle, profile.key
            )));
        }
        Ok(ProfiledMonitor {
            link: self,
            profile,
            last: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const G5_CAPS: &str = "(prot(monitor)type(lcd)model(LEMON23)cmds(01 02 03 07 0C E3 F3)vcp(02 04 05 08 10 12 14(05 08 0B 0C) 16 18 1A 52 60(11 0F ) 62 87 8D CC mswhql(1)mccs_ver(2.0)asset_eep(32)mpu_ver(01))";
    const LC34_CAPS: &str = "(prot(monitor)type(lcd)SAMSUNGcmds(01 02 03 07 0C E3 F3)vcp(02 04 05 08 10 12 14(05 08 0B 0C) 16 18 1A 52 60( 12 0F 10) AA(01 02 03 FF) AC AE B2 B6 C6 C8 C9 D6(01 04 05) DC(00 02 03 05 ) DF FD)mccs_ver(2.1)mswhql(1))";

    #[test]
    fn parses_input_values_from_real_capabilities() {
        assert_eq!(caps_values(G5_CAPS, 0x60), Some(vec![0x11, 0x0F]));
        assert_eq!(caps_values(LC34_CAPS, 0x60), Some(vec![0x12, 0x0F, 0x10]));
        assert_eq!(caps_values(LC34_CAPS, 0xD6), Some(vec![1, 4, 5]));
        assert_eq!(caps_values(G5_CAPS, 0xD6), None);
        // 0x14's list contains "0C": a value inside a list is not a code.
        assert_eq!(caps_values(G5_CAPS, 0x0C), None);
    }

    #[test]
    fn g5_profile_matches_only_g5_capabilities() {
        let g5 = &PROFILES[0];
        assert!(g5.matches_capabilities(G5_CAPS));
        assert!(!g5.matches_capabilities(LC34_CAPS));
        assert!(!g5.matches_capabilities("garbage"));
    }
}
