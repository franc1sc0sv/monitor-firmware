"""Event-log protocol on top of plain MCCS Get/Set VCP.

VCP codes (manufacturer range):
  0xEA get: MH=ring size, ML=protocol version, CH:CL=sequence number of the newest event
  0xEB set/get: cursor (sequence number of the event to read)
  0xEC get: event at cursor: MH=id, ML=old, CH=new, CL=low byte of the event's sequence number
  0xED get: event time: MH=low byte of sequence number, ML:CH:CL=time in 10 ms units since boot
  0xEE get: live state: MH=input port, ML=source select, CH=power flags, CL=signal present
  0xEF get: monitor clock, 32-bit, 10 ms units since boot
"""

from __future__ import annotations

import time
from dataclasses import dataclass

EVENT_NAMES = {
    0x00: "boot",
    0x01: "input-port",
    0x02: "source-select",
    0x03: "power-flags",
    0x04: "powersave-flags",
    0x05: "sync-flags",
    0x06: "signal",
    0x07: "system-state",
    0x08: "window-port",
    0x10: "ddc-switch-request",
    0x11: "switch-done",
    0x12: "switch-failed",
    0x13: "ddc-power-request",
    0x20: "setting-changed",
    0x21: "setting-changed",
}
SETTINGS_BASE = 0x204000
# Factory identity inside the settings block: model string at +0x89, serial number copies at +0x9a..+0xb9.
# Masked by default in every output so dumps can be pasted into issues safely.
SERIAL_MASK = range(0x9A, 0xBA)

# One table for every known VCP code (name, readable value?). Used by the CLI, the server and the UI.
VCP_CODES = {
    0x10: "brightness",
    0x12: "contrast",
    0x14: "color preset",
    0x16: "red gain",
    0x18: "green gain",
    0x1A: "blue gain",
    0x20: "h-position",
    0x30: "v-position",
    0x52: "active control",
    0x60: "input",
    0x62: "volume",
    0x87: "sharpness",
    0x8D: "mute",
    0xAA: "orientation",
    0xAC: "h-frequency",
    0xAE: "v-frequency",
    0xB2: "subpixel layout",
    0xB6: "panel type",
    0xC6: "app enable key",
    0xC8: "controller type",
    0xC9: "firmware level",
    0xCC: "OSD language",
    0xD6: "power mode",
    0xDB: "samsung DB",
    0xDC: "picture mode",
    0xDF: "VCP version",
    0xE0: "samsung E0",
    0xE7: "samsung E7",
    0xF7: "energy mode (samsung F7)",
    0xFD: "samsung FD",
}
# Codes whose Get does not return the value just written (action codes or values the firmware rewrites).
NO_READBACK = {0x04, 0x05, 0x08, 0x60, 0xD6, 0xF7}


def mask_serial(addr: int, data: bytes, raw: bool = False) -> bytes:
    """Replaces the serial-number bytes with 0x2A ('*') when [addr, addr+len) overlaps them."""
    if raw:
        return data
    out = bytearray(data)
    for i in range(len(out)):
        if (addr + i - SETTINGS_BASE) in SERIAL_MASK:
            out[i] = 0x2A
    return bytes(out)


# Settings offsets identified so far (offset from 0x204000). Extended as more are mapped.
SETTING_NAMES = {
    0xD7: "power/ddc flags (bit0 power on, bit6 DDC/CI enabled)",
    0xDE: "source select",
    0xE4: "current window",
    0xE5: "window 0 input port",
    0x1D3: "brightness (menu item 0x0d)",
    0x1D6: "samsung VCP F7 (item 0x31)",
    0x1D7: "red gain (item 0x11)",
    0x1D8: "green gain (item 0x12)",
    0x1D9: "blue gain (item 0x13)",
    0x1DA: "contrast (item 0x0e)",
    0x1DF: "sharpness (item 0x0f)",
    0x1E0: "samsung VCP F3 (item 0x04)",
}
# menu item to apply after poking a setting (FullAccess.apply)
SETTING_ITEMS = {0x1D3: 0x0D, 0x1D6: 0x31, 0x1D7: 0x11, 0x1D8: 0x12, 0x1D9: 0x13, 0x1DA: 0x0E, 0x1DF: 0x0F, 0x1E0: 0x04}
PORT_NAMES = {0: "DisplayPort", 1: "HDMI", 2: "port2"}
VCP_TO_PORT = {0x09: 0, 0x06: 1}
PORT_TO_VCP = {v: k for k, v in VCP_TO_PORT.items()}


@dataclass
class Event:
    seq: int
    id: int
    old: int
    new: int
    time_10ms: int

    @property
    def name(self) -> str:
        return EVENT_NAMES.get(self.id, f"id-0x{self.id:02x}")

    @property
    def seconds(self) -> float:
        return self.time_10ms / 100.0

    def describe(self) -> str:
        if self.id in (0x01,):
            return (
                f"input changed {PORT_NAMES.get(self.old, hex(self.old))} to {PORT_NAMES.get(self.new, hex(self.new))}"
            )
        if self.id == 0x06:
            return "signal " + ("present" if self.new else "lost")
        if self.id == 0x10:
            return f"switch requested over DDC to VCP 0x{self.new:02x} (from {PORT_NAMES.get(self.old, hex(self.old))})"
        if self.id == 0x11:
            return f"switch done: now on {PORT_NAMES.get(self.new, hex(self.new))}"
        if self.id == 0x12:
            return f"switch FAILED: wanted {PORT_NAMES.get(self.old, hex(self.old))}, still on {PORT_NAMES.get(self.new, hex(self.new))}"
        if self.id == 0x03:
            return f"power flags 0x{self.old:02x} to 0x{self.new:02x} (power {'on' if self.new & 1 else 'off'})"
        if self.id == 0x00:
            return "monitor booted (event log started)"
        if self.id in (0x20, 0x21):
            off = ((self.id & 1) << 8) | self.old
            return f"setting 0x{SETTINGS_BASE + off:06x} ({SETTING_NAMES.get(off, f'offset 0x{off:03x}')}) = {self.new} (0x{self.new:02x})"
        return f"{self.name} 0x{self.old:02x} to 0x{self.new:02x}"


@dataclass
class LiveState:
    port: int
    source_select: int
    power_flags: int
    signal: int
    clock_10ms: int

    @property
    def power_on(self) -> bool:
        return bool(self.power_flags & 1)


class ProtocolError(Exception):
    pass


class EventLog:
    """One monitor, possibly reachable over several cables (e.g. HDMI on one GPU and DP on another).
    Requests go to the first path that answers; while the monitor retrains a link, the other path keeps working."""

    def __init__(self, display, retries: int = 4, extra_paths=()):
        self.paths = [display, *extra_paths]
        self.retries = retries

    @property
    def d(self):
        return self.paths[0]

    def _rotate(self):
        if len(self.paths) > 1:
            self.paths.append(self.paths.pop(0))

    def _get(self, code: int):
        last = None
        for _ in range(self.retries * len(self.paths)):
            try:
                r = self.d.get_vcp_raw(code)
                if r is not None:
                    return r
            except OSError as e:  # transient bus errors
                last = e
            self._rotate()
            time.sleep(0.03)
        raise ProtocolError(f"no valid reply to VCP 0x{code:02x}" + (f": {last}" if last else ""))

    def get_vcp(self, code: int):
        """Public: (rc, mh, ml, ch, cl) for any VCP code, with retries and path failover."""
        return self._get(code)

    def set_vcp(self, code: int, value: int, confirm: bool = True) -> dict:
        """Public: write a VCP code; when the code is readable, read back until it sticks."""
        for attempt in range(1, 6):
            self._set(code, value)
            if not confirm or code in NO_READBACK:
                return {"code": code, "attempts": attempt, "confirmed": False}
            time.sleep(0.12)
            try:
                rc, mh, ml, ch, cl = self._get(code)
            except ProtocolError:
                continue
            if rc != 0:
                return {"code": code, "attempts": attempt, "confirmed": False, "supported": False}
            if (ch << 8) | cl == value:
                return {"code": code, "attempts": attempt, "confirmed": True, "current": value, "max": (mh << 8) | ml}
        raise ProtocolError(f"VCP 0x{code:02x} = {value} not confirmed after 5 attempts")

    def _set(self, code: int, value: int):
        for _ in range(self.retries * len(self.paths)):
            try:
                self.d.set_vcp(code, value)
                return
            except OSError:
                self._rotate()
                time.sleep(0.03)
        raise ProtocolError(f"could not set VCP 0x{code:02x}")

    def supported(self) -> bool:
        try:
            rc, mh, ml, ch, cl = self._get(0xEA)
            return rc == 0 and mh == 0x40 and ml >= 2
        except ProtocolError:
            return False

    def info(self):
        rc, mh, ml, ch, cl = self._get(0xEA)
        if rc != 0:
            raise ProtocolError("VCP 0xEA unsupported: stock firmware?")
        return {"ring": mh, "version": ml, "seq": (ch << 8) | cl}

    def clock(self) -> int:
        rc, mh, ml, ch, cl = self._get(0xEF)
        return (mh << 24) | (ml << 16) | (ch << 8) | cl

    def live(self) -> LiveState:
        rc, mh, ml, ch, cl = self._get(0xEE)
        return LiveState(mh, ml, ch, cl, self.clock())

    def event(self, seq: int) -> Event:
        for _ in range(self.retries):
            self._set(0xEB, seq & 0xFFFF)
            _, eid, old, new, slo = self._get(0xEC)
            _, tlo, t2, t1, t0 = self._get(0xED)
            if slo == seq & 0xFF and tlo == seq & 0xFF:
                return Event(seq & 0xFFFF, eid, old, new, (t2 << 16) | (t1 << 8) | t0)
        raise ProtocolError(f"could not read event #{seq}")

    def history(self, last: int = 64):
        inf = self.info()
        seq, ring = inf["seq"], inf["ring"]
        n = min(last, ring, seq)
        return [self.event((seq - n + 1 + i) & 0xFFFF) for i in range(n)]

    def watch(self, interval: float = 0.25, since: int | None = None):
        """Yield events as they happen. Detects ring overflow (gap larger than the ring)."""
        last = self.info()["seq"] if since is None else since
        while True:
            try:
                inf = self.info()
            except ProtocolError:
                time.sleep(interval)
                continue
            cur = inf["seq"]
            gap = (cur - last) & 0xFFFF
            if gap > inf["ring"]:
                yield Event(0, 0xFF, 0, gap - inf["ring"], 0)  # lost events marker
                last = (cur - inf["ring"]) & 0xFFFF
                gap = inf["ring"]
            try:
                for _ in range(gap):
                    e = self.event((last + 1) & 0xFFFF)
                    last = (last + 1) & 0xFFFF
                    yield e
            except ProtocolError:
                self._rotate()
            time.sleep(interval)

    # ---- actions
    def switch_input(self, port: int, timeout: float = 12.0) -> Event:
        """Ask the monitor to switch and wait for the firmware's own verdict (switch-done / switch-failed)."""
        start = self.info()["seq"]
        self._set(0x60, PORT_TO_VCP[port])
        deadline = time.time() + timeout
        last = start
        while time.time() < deadline:
            try:
                cur = self.info()["seq"]
                while last != cur:
                    nxt = (last + 1) & 0xFFFF
                    e = self.event(nxt)
                    last = nxt
                    if e.id in (0x11, 0x12):
                        return e
            except ProtocolError:
                self._rotate()  # link retraining on this path; keep waiting for the firmware's verdict
            time.sleep(0.1)
        raise ProtocolError("no switch verdict from the monitor (asked from an input it no longer answers on?)")


class FullAccess:
    """v3 memory/menu access: Set 0xF0/0xF1 address halves, Get 0xF2 reads 4 bytes (auto-increment),
    Set 0xF4 writes one byte inside 0x204000..0x2043ff (auto-increment), Set 0xF6 applies menu item N."""

    def __init__(self, log: EventLog):
        self.log = log

    def _addr(self, addr: int):
        self.log._set(0xF0, (addr >> 16) & 0xFFFF)
        self.log._set(0xF1, addr & 0xFFFF)

    def _read_addr(self) -> int:
        hi = self.log._get(0xF0)
        lo = self.log._get(0xF1)
        return (hi[3] << 24) | (hi[4] << 16) | (lo[3] << 8) | lo[4]

    def peek(self, addr: int, length: int, block: int = 64) -> bytes:
        """Reads in blocks: set the address once, read words sequentially (the firmware auto-increments),
        then confirm the address advanced exactly; a lost or duplicated read makes the block retry."""
        out = bytearray()
        a0 = addr & ~3
        end = addr + length
        a = a0
        while a < end:
            n = min(block, ((end - a) + 3) & ~3)
            for _ in range(5):
                self._addr(a)
                chunk = bytearray()
                for _ in range(n // 4):
                    rc, b0, b1, b2, b3 = self.log._get(0xF2)
                    chunk += bytes([b0, b1, b2, b3])
                if self._read_addr() == a + n:
                    break
            else:
                raise ProtocolError(f"peek failed at 0x{a:06x}")
            out += chunk
            a += n
        return bytes(out[addr - a0 : addr - a0 + length])

    def poke(self, addr: int, value: int):
        if not (0x204000 <= addr < 0x204400):
            raise ValueError("firmware only accepts writes in 0x204000..0x2043ff")
        for _ in range(4):
            self._addr(addr)
            self.log._set(0xF4, value & 0xFF)
            if self.peek(addr, 1)[0] == value & 0xFF:
                return
        raise ProtocolError(f"poke 0x{addr:06x} not confirmed")

    def apply(self, item: int):
        if not 0 <= item <= 0x6E:
            raise ValueError("menu item 0..0x6e")
        self.log._set(0xF6, item)

    def settings(self, raw: bool = False) -> bytes:
        return mask_serial(SETTINGS_BASE, self.peek(SETTINGS_BASE, 0x400), raw)

    def peek_masked(self, addr: int, length: int, raw: bool = False) -> bytes:
        return mask_serial(addr, self.peek(addr, length), raw)
