//! macOS backend (Apple Silicon): DDC/CI over the private `IOAVService` I2C API, the one m1ddc and
//! MonitorControl use. Every symbol is resolved at run time with `dlsym`, so a macOS without them (or an
//! Intel Mac) builds and links fine and reports "no channel" instead.
//!
//! Known limit (confirmed on the 34"): over HDMI the monitor only answers while HDMI is the active input.

use std::ffi::{CStr, c_char, c_void};
use std::sync::{Mutex, MutexGuard};
use std::thread::sleep;
use std::time::Duration;

use crate::bus::{DdcBus, MonitorHandle, MonitorInfo, VcpReply};
use crate::edid::Edid;
use crate::error::DdcError;
use crate::wire;

type CFTypeRef = *const c_void;
const UTF8: u32 = 0x0800_0100;
/// `kIOMainPortDefault`.
const MAIN_PORT: u32 = 0;
/// Request to reply: the protocol asks for 50-150 ms.
const REPLY_WAIT: Duration = Duration::from_millis(50);
/// The DCP drops a write now and then; one more try fixes it.
const WRITE_TRIES: usize = 2;
/// Upper bound for a capabilities string, in fragments (each up to 32 bytes).
const MAX_FRAGMENTS: usize = 256;

type ServiceMatchingFn = unsafe extern "C" fn(*const c_char) -> CFTypeRef;
type GetMatchingServicesFn = unsafe extern "C" fn(u32, CFTypeRef, *mut u32) -> i32;
type IteratorNextFn = unsafe extern "C" fn(u32) -> u32;
type ObjectReleaseFn = unsafe extern "C" fn(u32) -> i32;
type CreateCfPropertyFn = unsafe extern "C" fn(u32, CFTypeRef, CFTypeRef, u32) -> CFTypeRef;
type AvCreateFn = unsafe extern "C" fn(CFTypeRef, u32) -> CFTypeRef;
type AvReadFn = unsafe extern "C" fn(CFTypeRef, u32, u32, *mut c_void, u32) -> i32;
type AvWriteFn = unsafe extern "C" fn(CFTypeRef, u32, u32, *const c_void, u32) -> i32;
type AvCopyEdidFn = unsafe extern "C" fn(CFTypeRef, *mut CFTypeRef) -> i32;
type StringCreateFn = unsafe extern "C" fn(CFTypeRef, *const c_char, u32) -> CFTypeRef;
type StringGetFn = unsafe extern "C" fn(CFTypeRef, *mut c_char, isize, u32) -> u8;
type GetTypeIdFn = unsafe extern "C" fn(CFTypeRef) -> usize;
type TypeIdFn = unsafe extern "C" fn() -> usize;
type DataLengthFn = unsafe extern "C" fn(CFTypeRef) -> isize;
type DataBytesFn = unsafe extern "C" fn(CFTypeRef) -> *const u8;
type ReleaseFn = unsafe extern "C" fn(CFTypeRef);

struct Api {
    service_matching: ServiceMatchingFn,
    get_matching_services: GetMatchingServicesFn,
    iterator_next: IteratorNextFn,
    object_release: ObjectReleaseFn,
    create_cf_property: CreateCfPropertyFn,
    av_create: AvCreateFn,
    av_read: AvReadFn,
    av_write: AvWriteFn,
    av_copy_edid: Option<AvCopyEdidFn>,
    string_create: StringCreateFn,
    string_get: StringGetFn,
    get_type_id: GetTypeIdFn,
    string_type_id: TypeIdFn,
    data_length: DataLengthFn,
    data_bytes: DataBytesFn,
    release: ReleaseFn,
}

fn open(path: &CStr) -> Result<*mut c_void, DdcError> {
    // SAFETY: `path` is NUL-terminated; dlopen of a system framework has no other preconditions.
    let lib = unsafe { libc::dlopen(path.as_ptr(), libc::RTLD_LAZY) };
    if lib.is_null() {
        return Err(DdcError::NoChannel(format!(
            "cannot load {}",
            path.to_string_lossy()
        )));
    }
    Ok(lib)
}

fn sym(lib: *mut c_void, name: &CStr) -> Result<*mut c_void, DdcError> {
    // SAFETY: `lib` is a live dlopen handle (never closed) and `name` is NUL-terminated.
    let p = unsafe { libc::dlsym(lib, name.as_ptr()) };
    if p.is_null() {
        return Err(DdcError::NoChannel(format!(
            "IOKit symbol {} not available",
            name.to_string_lossy()
        )));
    }
    Ok(p)
}

/// Turns a resolved symbol into a typed function pointer.
macro_rules! load {
    ($lib:expr, $name:expr, $ty:ty) => {{
        let p = sym($lib, $name)?;
        // SAFETY: the symbol has this C signature in IOKit/CoreFoundation (the same declarations m1ddc
        // uses); data and function pointers have the same size on every Apple target.
        unsafe { std::mem::transmute::<*mut c_void, $ty>(p) }
    }};
}

impl Api {
    fn load() -> Result<Self, DdcError> {
        let io = open(c"/System/Library/Frameworks/IOKit.framework/IOKit")?;
        let cf = open(c"/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")?;
        Ok(Self {
            service_matching: load!(io, c"IOServiceMatching", ServiceMatchingFn),
            get_matching_services: load!(
                io,
                c"IOServiceGetMatchingServices",
                GetMatchingServicesFn
            ),
            iterator_next: load!(io, c"IOIteratorNext", IteratorNextFn),
            object_release: load!(io, c"IOObjectRelease", ObjectReleaseFn),
            create_cf_property: load!(io, c"IORegistryEntryCreateCFProperty", CreateCfPropertyFn),
            av_create: load!(io, c"IOAVServiceCreateWithService", AvCreateFn),
            av_read: load!(io, c"IOAVServiceReadI2C", AvReadFn),
            av_write: load!(io, c"IOAVServiceWriteI2C", AvWriteFn),
            av_copy_edid: sym(io, c"IOAVServiceCopyEDID").ok().map(|p| {
                // SAFETY: as in `load!`: `IOReturn IOAVServiceCopyEDID(IOAVServiceRef, CFDataRef *)`.
                unsafe { std::mem::transmute::<*mut c_void, AvCopyEdidFn>(p) }
            }),
            string_create: load!(cf, c"CFStringCreateWithCString", StringCreateFn),
            string_get: load!(cf, c"CFStringGetCString", StringGetFn),
            get_type_id: load!(cf, c"CFGetTypeID", GetTypeIdFn),
            string_type_id: load!(cf, c"CFStringGetTypeID", TypeIdFn),
            data_length: load!(cf, c"CFDataGetLength", DataLengthFn),
            data_bytes: load!(cf, c"CFDataGetBytePtr", DataBytesFn),
            release: load!(cf, c"CFRelease", ReleaseFn),
        })
    }

    /// `Location` property of a registry entry, if it is a string.
    fn location(&self, service: u32) -> Option<String> {
        // SAFETY: CoreFoundation calls with valid arguments; every created object is released below.
        unsafe {
            let key = (self.string_create)(std::ptr::null(), c"Location".as_ptr(), UTF8);
            if key.is_null() {
                return None;
            }
            let prop = (self.create_cf_property)(service, key, std::ptr::null(), 0);
            (self.release)(key);
            if prop.is_null() {
                return None;
            }
            let mut buf = [0 as c_char; 64];
            let ok = (self.get_type_id)(prop) == (self.string_type_id)()
                && (self.string_get)(prop, buf.as_mut_ptr(), buf.len() as isize, UTF8) != 0;
            (self.release)(prop);
            ok.then(|| CStr::from_ptr(buf.as_ptr()).to_string_lossy().into_owned())
        }
    }

    fn edid(&self, avs: CFTypeRef) -> Option<Vec<u8>> {
        let copy = self.av_copy_edid?;
        let mut data: CFTypeRef = std::ptr::null();
        // SAFETY: `avs` was just created by `monitors()`, which holds the state lock, so it is live;
        // `data` receives a +1 CFData that is released below.
        unsafe {
            if copy(avs, &mut data) != 0 || data.is_null() {
                return None;
            }
            let len = usize::try_from((self.data_length)(data)).unwrap_or(0);
            let ptr = (self.data_bytes)(data);
            let bytes = if ptr.is_null() {
                Vec::new()
            } else {
                std::slice::from_raw_parts(ptr, len).to_vec()
            };
            (self.release)(data);
            Some(bytes)
        }
    }
}

/// A monitor's service together with the bus lock that keeps it alive.
struct Locked<'a> {
    _guard: MutexGuard<'a, State>,
    avs: CFTypeRef,
}

#[derive(Default)]
struct State {
    next: u64,
    /// IOAVService objects from the last enumeration, as integers so the bus is `Send`.
    open: Vec<(MonitorHandle, usize)>,
}

/// DDC/CI through IOAVService on Apple Silicon.
pub struct MacBus {
    api: Api,
    state: Mutex<State>,
}

impl MacBus {
    /// `Err(NoChannel)` when IOAVService is not available on this macOS.
    pub fn new() -> Result<Self, DdcError> {
        Ok(Self {
            api: Api::load()?,
            state: Mutex::default(),
        })
    }

    fn lock(&self) -> Result<MutexGuard<'_, State>, DdcError> {
        self.state
            .lock()
            .map_err(|_| DdcError::NoChannel("bus state poisoned".into()))
    }

    /// Locks the bus and finds the monitor's service. The lock stays held as long as the returned
    /// [`Locked`] lives, which covers the whole request: `monitors()` and `Drop` release services only
    /// under this lock, so the service cannot be freed mid-I/O. It also keeps each I2C write/read pair
    /// (and multi-request sequences from other threads) from interleaving.
    fn service(&self, monitor: MonitorHandle) -> Result<Locked<'_>, DdcError> {
        let guard = self.lock()?;
        let avs = guard
            .open
            .iter()
            .find(|(h, _)| *h == monitor)
            .map(|(_, raw)| *raw as CFTypeRef)
            .ok_or(DdcError::UnknownMonitor(monitor))?;
        Ok(Locked { _guard: guard, avs })
    }

    fn write(&self, svc: &Locked<'_>, msg: &[u8], code: u8) -> Result<(), DdcError> {
        for _ in 0..WRITE_TRIES {
            // SAFETY: `svc.avs` is in `state.open` and `svc` holds the state lock, so the service is not
            // released during the call; `msg` is valid for `msg.len()` bytes.
            let rc = unsafe {
                (self.api.av_write)(
                    svc.avs,
                    u32::from(wire::DDC_ADDRESS),
                    u32::from(wire::HOST_ADDRESS),
                    msg.as_ptr().cast(),
                    msg.len() as u32,
                )
            };
            if rc == 0 {
                return Ok(());
            }
            sleep(Duration::from_millis(10));
        }
        Err(DdcError::Bus {
            code,
            detail: "IOAVServiceWriteI2C failed".into(),
        })
    }

    fn read(&self, svc: &Locked<'_>, len: usize, code: u8) -> Result<Vec<u8>, DdcError> {
        let mut buf = vec![0u8; len];
        // SAFETY: `svc.avs` is in `state.open` and `svc` holds the state lock, so the service is not
        // released during the call; `buf` has `len` writable bytes.
        let rc = unsafe {
            (self.api.av_read)(
                svc.avs,
                u32::from(wire::DDC_ADDRESS),
                u32::from(wire::HOST_ADDRESS),
                buf.as_mut_ptr().cast(),
                len as u32,
            )
        };
        if rc != 0 {
            return Err(DdcError::NoReply { code });
        }
        Ok(buf)
    }

    fn release_all(&self, open: &mut Vec<(MonitorHandle, usize)>) {
        for (_, raw) in open.drain(..) {
            // SAFETY: each object came from IOAVServiceCreateWithService (+1) and is released once.
            unsafe { (self.api.release)(raw as CFTypeRef) };
        }
    }
}

impl Drop for MacBus {
    fn drop(&mut self) {
        let mut open = match self.state.get_mut() {
            Ok(s) => std::mem::take(&mut s.open),
            Err(_) => return,
        };
        self.release_all(&mut open);
    }
}

impl DdcBus for MacBus {
    fn monitors(&self) -> Result<Vec<MonitorInfo>, DdcError> {
        let mut s = self.lock()?;
        let mut old = std::mem::take(&mut s.open);
        self.release_all(&mut old);
        let mut iter = 0u32;
        // SAFETY: the matching dictionary is consumed by IOServiceGetMatchingServices; `iter` is a valid
        // out pointer and is released after the loop.
        let rc = unsafe {
            let matching = (self.api.service_matching)(c"DCPAVServiceProxy".as_ptr());
            if matching.is_null() {
                return Err(DdcError::NoChannel("IOServiceMatching failed".into()));
            }
            (self.api.get_matching_services)(MAIN_PORT, matching, &mut iter)
        };
        if rc != 0 {
            return Err(DdcError::NoChannel(format!(
                "IOServiceGetMatchingServices failed ({rc})"
            )));
        }
        let mut out = Vec::new();
        loop {
            // SAFETY: `iter` is a live io_iterator_t.
            let service = unsafe { (self.api.iterator_next)(iter) };
            if service == 0 {
                break;
            }
            if self.api.location(service).as_deref() == Some("External") {
                // SAFETY: `service` is a live registry entry; the result is +1 and owned by `s.open`.
                let avs = unsafe { (self.api.av_create)(std::ptr::null(), service) };
                if !avs.is_null() {
                    s.next += 1;
                    let handle = MonitorHandle(s.next);
                    s.open.push((handle, avs as usize));
                    let edid = self.api.edid(avs).and_then(|b| Edid::parse(&b).ok());
                    let description = edid
                        .as_ref()
                        .and_then(|e| e.name().map(str::to_string))
                        .unwrap_or_else(|| format!("external display {}", out.len() + 1));
                    out.push(MonitorInfo {
                        handle,
                        description,
                        edid,
                    });
                }
            }
            // SAFETY: `service` came from IOIteratorNext and is released once.
            unsafe { (self.api.object_release)(service) };
        }
        // SAFETY: `iter` came from IOServiceGetMatchingServices and is released once.
        unsafe { (self.api.object_release)(iter) };
        Ok(out)
    }

    fn get_vcp(&self, monitor: MonitorHandle, code: u8) -> Result<VcpReply, DdcError> {
        let svc = self.service(monitor)?;
        self.write(&svc, &wire::get_vcp_request(code), code)?;
        sleep(REPLY_WAIT);
        let buf = self.read(&svc, wire::VCP_REPLY_LEN + 1, code)?;
        wire::parse_vcp_reply(&buf, code)
    }

    fn set_vcp(&self, monitor: MonitorHandle, code: u8, value: u16) -> Result<(), DdcError> {
        let svc = self.service(monitor)?;
        self.write(&svc, &wire::set_vcp_request(code, value), code)?;
        sleep(REPLY_WAIT);
        Ok(())
    }

    fn capabilities(&self, monitor: MonitorHandle) -> Result<String, DdcError> {
        let svc = self.service(monitor)?;
        let code = wire::CAPABILITIES_CODE;
        let mut out = Vec::new();
        for _ in 0..MAX_FRAGMENTS {
            let offset = u16::try_from(out.len())
                .map_err(|_| DdcError::Protocol("capabilities too long".into()))?;
            self.write(&svc, &wire::capabilities_request(offset), code)?;
            sleep(REPLY_WAIT);
            let buf = self.read(&svc, wire::CAPABILITIES_REPLY_LEN, code)?;
            let chunk = wire::parse_capabilities_fragment(&buf, offset)?;
            if chunk.is_empty() {
                break;
            }
            out.extend_from_slice(&chunk);
        }
        let end = out.iter().position(|b| *b == 0).unwrap_or(out.len());
        Ok(String::from_utf8_lossy(&out[..end]).into_owned())
    }
}
