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
    0x00: "boot", 0x01: "input-port", 0x02: "source-select", 0x03: "power-flags", 0x04: "powersave-flags",
    0x05: "sync-flags", 0x06: "signal", 0x07: "system-state", 0x08: "window-port",
    0x10: "ddc-switch-request", 0x11: "switch-done", 0x12: "switch-failed", 0x13: "ddc-power-request",
    0x20: "setting-changed", 0x21: "setting-changed",
}
SETTINGS_BASE = 0x204000
# Settings offsets identified so far (offset from 0x204000). Extended as more are mapped.
SETTING_NAMES = {
    0xd7: "power/ddc flags (bit0 power on, bit6 DDC/CI enabled)", 0xde: "source select", 0xe4: "current window",
    0xe5: "window 0 input port",
    0x1d3: "brightness (menu item 0x0d)", 0x1d6: "samsung VCP F7 (item 0x31)", 0x1d7: "red gain (item 0x11)",
    0x1d8: "green gain (item 0x12)", 0x1d9: "blue gain (item 0x13)", 0x1da: "contrast (item 0x0e)",
    0x1df: "sharpness (item 0x0f)", 0x1e0: "samsung VCP F3 (item 0x04)",
}
# menu item to apply after poking a setting (FullAccess.apply)
SETTING_ITEMS = {0x1d3: 0x0d, 0x1d6: 0x31, 0x1d7: 0x11, 0x1d8: 0x12, 0x1d9: 0x13, 0x1da: 0x0e, 0x1df: 0x0f, 0x1e0: 0x04}
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
            return f"input changed {PORT_NAMES.get(self.old, hex(self.old))} to {PORT_NAMES.get(self.new, hex(self.new))}"
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
            return f"setting 0x{SETTINGS_BASE + off:06x} ({SETTING_NAMES.get(off, 'offset 0x%03x' % off)}) = {self.new} (0x{self.new:02x})"
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
        hi = self.log._get(0xF0); lo = self.log._get(0xF1)
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
        return bytes(out[addr - a0: addr - a0 + length])

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

    def settings(self) -> bytes:
        return self.peek(SETTINGS_BASE, 0x400)
