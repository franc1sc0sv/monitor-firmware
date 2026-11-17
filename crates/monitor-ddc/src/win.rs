//! Windows backend: dxva2 (Monitor Configuration API) for VCP, SetupAPI + registry for the EDID.
//! Works with any GPU driver; DDC over DisplayPort stays alive whatever input the monitor shows.

use std::sync::Mutex;

use windows::Win32::Devices::DeviceAndDriverInstallation::{
    DICS_FLAG_GLOBAL, DIGCF_DEVICEINTERFACE, DIGCF_PRESENT, DIREG_DEV, HDEVINFO, SP_DEVINFO_DATA,
    SetupDiDestroyDeviceInfoList, SetupDiEnumDeviceInfo, SetupDiGetClassDevsW,
    SetupDiGetDeviceInstanceIdW, SetupDiOpenDevRegKey,
};
use windows::Win32::Devices::Display::{
    CapabilitiesRequestAndCapabilitiesReply, DestroyPhysicalMonitor, GUID_DEVINTERFACE_MONITOR,
    GetCapabilitiesStringLength, GetNumberOfPhysicalMonitorsFromHMONITOR,
    GetPhysicalMonitorsFromHMONITOR, GetVCPFeatureAndVCPFeatureReply, PHYSICAL_MONITOR,
    SetVCPFeature,
};
use windows::Win32::Foundation::{ERROR_SUCCESS, GetLastError, HANDLE, LPARAM, RECT};
use windows::Win32::Graphics::Gdi::{
    DISPLAY_DEVICE_ACTIVE, DISPLAY_DEVICEW, EnumDisplayDevicesW, EnumDisplayMonitors,
    GetMonitorInfoW, HDC, HMONITOR, MONITORINFOEXW,
};
use windows::Win32::System::Registry::{KEY_READ, RegCloseKey, RegQueryValueExW};
use windows::core::{BOOL, PCWSTR, w};

use crate::bus::{DdcBus, MonitorHandle, MonitorInfo, VcpReply};
use crate::edid::Edid;
use crate::error::DdcError;
use crate::win_path::instance_id_from_interface;

/// `EDD_GET_DEVICE_INTERFACE_NAME`: makes `DeviceID` the monitor's device interface path.
const EDD_GET_DEVICE_INTERFACE_NAME: u32 = 1;
/// `ERROR_GRAPHICS_DDCCI_VCP_NOT_SUPPORTED`, what dxva2 reports for an MCCS "unsupported" reply.
const VCP_NOT_SUPPORTED: u32 = 0xC026_2584;

#[derive(Default)]
struct State {
    next: u64,
    /// Physical monitor handles from the last enumeration, kept as integers so the bus is `Send`.
    open: Vec<(MonitorHandle, usize)>,
}

/// DDC/CI through dxva2. Physical monitor handles are owned here and destroyed on re-enumeration.
#[derive(Default)]
pub struct WindowsBus {
    state: Mutex<State>,
}

impl WindowsBus {
    pub fn new() -> Self {
        Self::default()
    }

    fn handle(&self, monitor: MonitorHandle) -> Result<HANDLE, DdcError> {
        let s = self
            .state
            .lock()
            .map_err(|_| DdcError::NoChannel("bus state poisoned".into()))?;
        s.open
            .iter()
            .find(|(h, _)| *h == monitor)
            .map(|(_, raw)| HANDLE(*raw as *mut _))
            .ok_or(DdcError::UnknownMonitor(monitor))
    }
}

impl Drop for WindowsBus {
    fn drop(&mut self) {
        if let Ok(s) = self.state.get_mut() {
            destroy_all(&mut s.open);
        }
    }
}

impl DdcBus for WindowsBus {
    fn monitors(&self) -> Result<Vec<MonitorInfo>, DdcError> {
        let mut s = self
            .state
            .lock()
            .map_err(|_| DdcError::NoChannel("bus state poisoned".into()))?;
        destroy_all(&mut s.open);
        let mut out = Vec::new();
        for hmon in display_monitors() {
            let edids = monitor_edids(hmon);
            for (i, (raw, description)) in physical_monitors(hmon).into_iter().enumerate() {
                s.next += 1;
                let handle = MonitorHandle(s.next);
                s.open.push((handle, raw));
                let edid = edids.get(i).and_then(|bytes| Edid::parse(bytes).ok());
                out.push(MonitorInfo {
                    handle,
                    description,
                    edid,
                });
            }
        }
        Ok(out)
    }

    fn get_vcp(&self, monitor: MonitorHandle, code: u8) -> Result<VcpReply, DdcError> {
        let h = self.handle(monitor)?;
        let (mut current, mut max) = (0u32, 0u32);
        // SAFETY: `h` is a live physical monitor handle owned by this bus; the out pointers are valid
        // locals for the duration of the call.
        let ok =
            unsafe { GetVCPFeatureAndVCPFeatureReply(h, code, None, &mut current, Some(&mut max)) };
        if ok == 0 {
            return Err(last_error(code));
        }
        Ok(VcpReply {
            max: (max & 0xFFFF) as u16,
            current: (current & 0xFFFF) as u16,
        })
    }

    fn set_vcp(&self, monitor: MonitorHandle, code: u8, value: u16) -> Result<(), DdcError> {
        let h = self.handle(monitor)?;
        // SAFETY: `h` is a live physical monitor handle owned by this bus.
        let ok = unsafe { SetVCPFeature(h, code, u32::from(value)) };
        if ok == 0 {
            return Err(last_error(code));
        }
        Ok(())
    }

    fn capabilities(&self, monitor: MonitorHandle) -> Result<String, DdcError> {
        let h = self.handle(monitor)?;
        let mut len = 0u32;
        // SAFETY: `h` is a live physical monitor handle; `len` is a valid out pointer.
        if unsafe { GetCapabilitiesStringLength(h, &mut len) } == 0 || len == 0 {
            return Err(last_error(0xF3));
        }
        let mut buf = vec![0u8; len as usize];
        // SAFETY: `buf` is exactly the length dxva2 asked for and outlives the call.
        if unsafe { CapabilitiesRequestAndCapabilitiesReply(h, &mut buf) } == 0 {
            return Err(last_error(0xF3));
        }
        let end = buf.iter().position(|b| *b == 0).unwrap_or(buf.len());
        Ok(String::from_utf8_lossy(&buf[..end]).into_owned())
    }
}

fn last_error(code: u8) -> DdcError {
    // SAFETY: reads the calling thread's last-error value; no pointers involved.
    let err = unsafe { GetLastError() };
    if err.0 == VCP_NOT_SUPPORTED {
        DdcError::Unsupported { code }
    } else {
        DdcError::Bus {
            code,
            detail: format!("dxva2 error 0x{:08x}", err.0),
        }
    }
}

fn destroy_all(open: &mut Vec<(MonitorHandle, usize)>) {
    for (_, raw) in open.drain(..) {
        // SAFETY: each handle came from GetPhysicalMonitorsFromHMONITOR and is destroyed exactly once
        // (drained from the list here).
        let _ = unsafe { DestroyPhysicalMonitor(HANDLE(raw as *mut _)) };
    }
}

unsafe extern "system" fn collect_monitor(
    hmon: HMONITOR,
    _: HDC,
    _: *mut RECT,
    data: LPARAM,
) -> BOOL {
    // SAFETY: `data` is the `&mut Vec<usize>` passed by `display_monitors`, alive during the enumeration.
    let list = unsafe { &mut *(data.0 as *mut Vec<usize>) };
    list.push(hmon.0 as usize);
    BOOL(1)
}

fn display_monitors() -> Vec<HMONITOR> {
    let mut list: Vec<usize> = Vec::new();
    // SAFETY: the callback only pushes into `list`, which outlives this synchronous call.
    let _ = unsafe {
        EnumDisplayMonitors(
            None,
            None,
            Some(collect_monitor),
            LPARAM(&mut list as *mut _ as isize),
        )
    };
    list.into_iter()
        .map(|raw| HMONITOR(raw as *mut _))
        .collect()
}

fn physical_monitors(hmon: HMONITOR) -> Vec<(usize, String)> {
    let mut count = 0u32;
    // SAFETY: `hmon` comes from EnumDisplayMonitors; `count` is a valid out pointer.
    if unsafe { GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, &mut count) }.is_err() || count == 0 {
        return Vec::new();
    }
    let mut arr = vec![PHYSICAL_MONITOR::default(); count as usize];
    // SAFETY: `arr` has room for exactly `count` entries.
    if unsafe { GetPhysicalMonitorsFromHMONITOR(hmon, &mut arr) }.is_err() {
        return Vec::new();
    }
    // PHYSICAL_MONITOR is packed: copy the fields out instead of borrowing them.
    arr.iter()
        .map(|p| {
            let handle = p.hPhysicalMonitor;
            let description = p.szPhysicalMonitorDescription;
            (handle.0 as usize, wide_to_string(&description))
        })
        .collect()
}

/// EDIDs of the monitors attached to this HMONITOR's display, in the same order as the physical monitors.
fn monitor_edids(hmon: HMONITOR) -> Vec<Vec<u8>> {
    let mut info = MONITORINFOEXW::default();
    info.monitorInfo.cbSize = size_of::<MONITORINFOEXW>() as u32;
    // SAFETY: `info` is a MONITORINFOEXW with cbSize set, as GetMonitorInfoW requires for the extended form.
    if !unsafe { GetMonitorInfoW(hmon, &mut info as *mut _ as *mut _) }.as_bool() {
        return Vec::new();
    }
    let adapter = info.szDevice;
    let mut out = Vec::new();
    for i in 0.. {
        let mut dd = DISPLAY_DEVICEW {
            cb: size_of::<DISPLAY_DEVICEW>() as u32,
            ..Default::default()
        };
        // SAFETY: `adapter` is a NUL-terminated device name from GetMonitorInfoW; `dd` has cb set.
        let found = unsafe {
            EnumDisplayDevicesW(
                PCWSTR(adapter.as_ptr()),
                i,
                &mut dd,
                EDD_GET_DEVICE_INTERFACE_NAME,
            )
        };
        if !found.as_bool() {
            break;
        }
        if dd.StateFlags.0 & DISPLAY_DEVICE_ACTIVE.0 == 0 {
            continue;
        }
        let edid = instance_id_from_interface(&wide_to_string(&dd.DeviceID))
            .and_then(|id| registry_edid(&id));
        out.push(edid.unwrap_or_default());
    }
    out
}

struct DevInfo(HDEVINFO);

impl Drop for DevInfo {
    fn drop(&mut self) {
        // SAFETY: the set came from SetupDiGetClassDevsW and is destroyed once.
        let _ = unsafe { SetupDiDestroyDeviceInfoList(self.0) };
    }
}

/// Reads `EDID` from the device registry key of the monitor whose instance id is `instance`.
fn registry_edid(instance: &str) -> Option<Vec<u8>> {
    // SAFETY: plain call with a static GUID; the returned set is owned by `DevInfo`.
    let set = DevInfo(
        unsafe {
            SetupDiGetClassDevsW(
                Some(&GUID_DEVINTERFACE_MONITOR),
                PCWSTR::null(),
                None,
                DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
            )
        }
        .ok()?,
    );
    for index in 0.. {
        let mut data = SP_DEVINFO_DATA {
            cbSize: size_of::<SP_DEVINFO_DATA>() as u32,
            ..Default::default()
        };
        // SAFETY: `data` has cbSize set; the set is alive.
        if unsafe { SetupDiEnumDeviceInfo(set.0, index, &mut data) }.is_err() {
            return None;
        }
        let mut id = [0u16; 512];
        // SAFETY: `id` is a writable buffer whose length the binding passes along.
        if unsafe { SetupDiGetDeviceInstanceIdW(set.0, &data, Some(&mut id), None) }.is_err() {
            continue;
        }
        if !wide_to_string(&id).eq_ignore_ascii_case(instance) {
            continue;
        }
        // SAFETY: `data` identifies a device of the live set; the key is closed below.
        let key = unsafe {
            SetupDiOpenDevRegKey(set.0, &data, DICS_FLAG_GLOBAL.0, 0, DIREG_DEV, KEY_READ.0)
        }
        .ok()?;
        let mut buf = vec![0u8; 1024];
        let mut len = buf.len() as u32;
        // SAFETY: `buf` has `len` writable bytes; `key` is an open registry key.
        let status = unsafe {
            RegQueryValueExW(
                key,
                w!("EDID"),
                None,
                None,
                Some(buf.as_mut_ptr()),
                Some(&mut len),
            )
        };
        // SAFETY: `key` was opened above and is closed once.
        let _ = unsafe { RegCloseKey(key) };
        if status != ERROR_SUCCESS {
            return None;
        }
        buf.truncate(len as usize);
        return Some(buf);
    }
    None
}

fn wide_to_string(w: &[u16]) -> String {
    let end = w.iter().position(|c| *c == 0).unwrap_or(w.len());
    String::from_utf16_lossy(&w[..end])
}
