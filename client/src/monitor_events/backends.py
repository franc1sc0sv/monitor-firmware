"""DDC/CI transports. Each display object exposes:
    name: str
    get_vcp_raw(code) -> (rc, mh, ml, ch, cl) or None when no valid reply
    set_vcp(code, value) -> None
"""
from __future__ import annotations
import sys
import time


def _ddc_reply_ok(r: bytes, code: int) -> bool:
    if len(r) < 11 or r[0] != 0x6E or r[1] != 0x88 or r[2] != 0x02 or r[4] != code:
        return False
    x = 0x50
    for b in r[:10]:
        x ^= b
    return x == r[10]


# ---------------------------------------------------------------- Windows: dxva2 (works with any GPU driver)
class _WinDisplay:
    def __init__(self, handle, desc, dxva):
        self.h, self.name, self.dxva = handle, desc, dxva

    def get_vcp_raw(self, code):
        import ctypes
        from ctypes import wintypes
        t, cur, mx = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        if not self.dxva.GetVCPFeatureAndVCPFeatureReply(self.h, code, ctypes.byref(t), ctypes.byref(cur), ctypes.byref(mx)):
            return None
        return (0, (mx.value >> 8) & 0xFF, mx.value & 0xFF, (cur.value >> 8) & 0xFF, cur.value & 0xFF)

    def set_vcp(self, code, value):
        if not self.dxva.SetVCPFeature(self.h, code, value):
            raise OSError(f"SetVCPFeature 0x{code:02x} failed")
        time.sleep(0.05)


def _windows_displays():
    import ctypes
    from ctypes import wintypes

    class PHYS(ctypes.Structure):
        _fields_ = [("h", wintypes.HANDLE), ("desc", wintypes.WCHAR * 128)]

    user32, dxva = ctypes.windll.user32, ctypes.windll.dxva2
    out = []
    MONENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.c_void_p, wintypes.LPARAM)

    def cb(hmon, hdc, rc, lp):
        n = wintypes.DWORD()
        if dxva.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(n)) and n.value:
            arr = (PHYS * n.value)()
            if dxva.GetPhysicalMonitorsFromHMONITOR(hmon, n.value, arr):
                for p in arr:
                    out.append(_WinDisplay(p.h, p.desc, dxva))
        return True

    user32.EnumDisplayMonitors(None, None, MONENUM(cb), 0)
    return out


# ---------------------------------------------------------------- Linux: /dev/i2c-* (i2c-dev), address 0x37
class _LinuxDisplay:
    I2C_SLAVE = 0x0703

    def __init__(self, path):
        self.path, self.name = path, path

    def _xfer(self, payload: bytes, read_len: int):
        import fcntl
        import os
        fd = os.open(self.path, os.O_RDWR)
        try:
            fcntl.ioctl(fd, self.I2C_SLAVE, 0x37)
            msg = bytes([0x51, 0x80 | len(payload)]) + payload
            chk = 0x6E
            for b in msg:
                chk ^= b
            os.write(fd, msg + bytes([chk]))
            if not read_len:
                return b""
            time.sleep(0.05)
            return os.read(fd, read_len)
        finally:
            os.close(fd)

    def get_vcp_raw(self, code):
        r = self._xfer(bytes([0x01, code]), 11)
        if not _ddc_reply_ok(r, code):
            return None
        return (r[3], r[6], r[7], r[8], r[9])

    def set_vcp(self, code, value):
        self._xfer(bytes([0x03, code, (value >> 8) & 0xFF, value & 0xFF]), 0)
        time.sleep(0.05)


def _linux_displays():
    import glob
    out = []
    for p in sorted(glob.glob("/dev/i2c-*")):
        out.append(_LinuxDisplay(p))
    return out


# ---------------------------------------------------------------- macOS (Apple Silicon): IOAVService I2C
# Same private API used by m1ddc / MonitorControl. Untested on this project's hardware so far.
class _MacDisplay:
    def __init__(self, avs, name, lib):
        self.avs, self.name, self.lib = avs, name, lib

    def _write(self, payload: bytes):
        import ctypes
        msg = bytes([0x80 | len(payload)]) + payload
        chk = 0x6E ^ 0x51
        for b in msg:
            chk ^= b
        buf = (ctypes.c_uint8 * (len(msg) + 1))(*(msg + bytes([chk])))
        for _ in range(2):  # the DCP drops the first write now and then
            if self.lib.IOAVServiceWriteI2C(self.avs, 0x37, 0x51, buf, len(msg) + 1) == 0:
                return
            time.sleep(0.01)
        raise OSError("IOAVServiceWriteI2C failed")

    def get_vcp_raw(self, code):
        import ctypes
        self._write(bytes([0x01, code]))
        time.sleep(0.05)
        buf = (ctypes.c_uint8 * 12)()
        if self.lib.IOAVServiceReadI2C(self.avs, 0x37, 0x51, buf, 12) != 0:
            return None
        r = bytes(buf)
        if r[0] != 0x6E:  # some paths return the reply without the source byte
            r = b"\x6e" + r[:11]
        if not _ddc_reply_ok(r, code):
            return None
        return (r[3], r[6], r[7], r[8], r[9])

    def set_vcp(self, code, value):
        self._write(bytes([0x03, code, (value >> 8) & 0xFF, value & 0xFF]))
        time.sleep(0.05)


def _mac_displays():
    import ctypes
    import ctypes.util
    iokit = ctypes.CDLL(ctypes.util.find_library("IOKit"))
    cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
    iokit.IOServiceMatching.restype = ctypes.c_void_p
    iokit.IOServiceGetMatchingServices.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    iokit.IOIteratorNext.restype = ctypes.c_uint32
    iokit.IORegistryEntryCreateCFProperty.restype = ctypes.c_void_p
    iokit.IORegistryEntryCreateCFProperty.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    iokit.IOAVServiceCreateWithService.restype = ctypes.c_void_p
    iokit.IOAVServiceCreateWithService.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    iokit.IOAVServiceWriteI2C.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    iokit.IOAVServiceReadI2C.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    utf8 = 0x08000100
    loc_key = cf.CFStringCreateWithCString(None, b"Location", utf8)
    it = ctypes.c_uint32()
    iokit.IOServiceGetMatchingServices(0, iokit.IOServiceMatching(b"DCPAVServiceProxy"), ctypes.byref(it))
    out, i = [], 0
    while True:
        svc = iokit.IOIteratorNext(it.value)
        if not svc:
            break
        prop = iokit.IORegistryEntryCreateCFProperty(svc, loc_key, None, 0)
        s = ctypes.create_string_buffer(64)
        if prop and cf.CFStringGetCString(prop, s, 64, utf8) and s.value == b"External":
            avs = iokit.IOAVServiceCreateWithService(None, svc)
            if avs:
                out.append(_MacDisplay(avs, f"external-{i}", iokit))
                i += 1
    return out


def open_displays():
    if sys.platform == "win32":
        return _windows_displays()
    if sys.platform == "darwin":
        return _mac_displays()
    return _linux_displays()
