//! Device path handling for the Windows backend, kept portable so it is tested on every platform.

/// `\\?\DISPLAY#SAM7155#5&1a2b3c&0&UID4352#{e6f07b5f-...}` -> `DISPLAY\SAM7155\5&1a2b3c&0&UID4352`,
/// the device instance id SetupAPI reports for the same monitor.
#[cfg_attr(not(windows), allow(dead_code))]
pub(crate) fn instance_id_from_interface(path: &str) -> Option<String> {
    let rest = path.strip_prefix(r"\\?\").unwrap_or(path);
    let rest = match rest.rfind("#{") {
        Some(at) => &rest[..at],
        None => rest,
    };
    let id = rest.replace('#', "\\");
    (id.matches('\\').count() == 2).then_some(id)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converts_monitor_interface_paths() {
        assert_eq!(
            instance_id_from_interface(
                r"\\?\DISPLAY#SAM7155#5&1a2b3c&0&UID4352#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}"
            )
            .as_deref(),
            Some(r"DISPLAY\SAM7155\5&1a2b3c&0&UID4352")
        );
        assert_eq!(instance_id_from_interface("garbage"), None);
    }
}
