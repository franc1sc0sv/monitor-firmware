"""FakeMonitor: an executable model of the patched firmware's DDC/CI interface (docs/protocol/vcp-interface.md).

It implements the same display interface as the real transports (`name`, `get_vcp_raw`, `set_vcp`), so the
protocol client, the CLI and the HTTP API run unchanged against it: tests use it, and
`monitor-events serve --simulate` lets anyone work on the UI without the hardware.
"""

from __future__ import annotations

import threading
import time

SETTINGS_BASE = 0x204000
SETTINGS_LEN = 0x400
RAM_LO, RAM_HI = 0x200000, 0x800000
RING = 64


class FakeMonitor:
    def __init__(
        self,
        name: str = "fake LC34G55T",
        port: int = 1,
        switch_delay: float = 0.3,
        lock_ok: bool = True,
        protocol: int = 3,
        cables: int = 0b11,
    ):
        self.name = name
        self.protocol = protocol  # 2 = firmware v3.1, 3 = v3.2
        self.cables = cables  # bit 0 DP, bit 1 HDMI
        self.soft = 0  # 0 on, 1 soft standby (protocol 3)
        self.off = False  # real power off: nothing answers
        self.port = port  # 0 DP, 1 HDMI
        self.switch_delay = switch_delay
        self.lock_ok = lock_ok  # False: switching never gets a locked picture -> switch-failed
        self.t0 = time.monotonic()
        self.mem = bytearray(RAM_HI - RAM_LO)
        self.vcp = {
            0x10: (99, 100),
            0x12: (85, 100),
            0x87: (15, 100),
            0x16: (42, 100),
            0x18: (44, 100),
            0x1A: (50, 100),
            0x14: (2, 5),
            0xF7: (2, 3),
        }
        self.seq = 0
        self.ring: list[tuple[int, int, int, int, int]] = [(0, 0, 0, 0, 0)] * RING
        self.cursor = 0
        self.addr = 0
        self.lock = threading.Lock()
        serial = b"FAKE0000000000"
        self.mem[SETTINGS_BASE - RAM_LO + 0x89 : SETTINGS_BASE - RAM_LO + 0x97] = b"LC34G55TWWNXZA"
        self.mem[SETTINGS_BASE - RAM_LO + 0x9A : SETTINGS_BASE - RAM_LO + 0x9A + len(serial)] = serial
        self._settings_set(0x1D3, 99)
        self._settings_set(0x0E5, port)
        self._log(0x00, 0, 0)
        if protocol >= 3:
            self._log(0x14, 0, 1)  # power-state on, cause cold boot
            self._log(0x15, 0xEE, cables)

    # ---- model helpers
    def clock(self) -> int:
        return int((time.monotonic() - self.t0) * 100) & 0xFFFFFFFF

    def _settings_set(self, off: int, value: int):
        self.mem[SETTINGS_BASE - RAM_LO + off] = value & 0xFF

    def _log(self, eid: int, old: int, new: int):
        self.seq = (self.seq + 1) & 0xFFFF
        self.ring[self.seq % RING] = (self.seq, eid, old & 0xFF, new & 0xFF, self.clock())

    def _switch(self, target: int, value: int):
        self._log(0x10, self.port, value)

        def run():
            time.sleep(self.switch_delay)
            with self.lock:
                old = self.port
                self.port = target
                self._settings_set(0x0E5, target)
                self._log(0x01, old, target)
                if self.lock_ok:
                    self._log(0x05, 0x0E, 0x0A)
                    self._log(0x11, target, target)
            if not self.lock_ok:
                time.sleep(self.switch_delay)
                with self.lock:
                    self._log(0x12, target, self.port)

        threading.Thread(target=run, daemon=True).start()

    # ---- things that happen at the monitor (protocol 3 model)
    def set_cables(self, mask: int):
        """A cable / source appears or goes away (bit 0 DP, bit 1 HDMI)."""
        with self.lock:
            if mask != self.cables:
                old, self.cables = self.cables, mask & 3
                if self.protocol >= 3:
                    self._log(0x15, old, self.cables)

    def press_key(self):
        """Any key in soft standby wakes the monitor (cause 2) and is not passed on to the stock handlers."""
        with self.lock:
            if self.soft:
                self.soft = 0
                self._log(0x14, 2, 1)

    def _set_power(self, value: int):
        self._log(0x13, self.port, value)
        if self.protocol < 3:
            self.off = value == 4  # stock: only 4 acts, and it is a real power off
            return
        if value == 4 and not self.soft:
            self.soft = 1
            self._log(0x14, 1, 4)
        elif value == 1 and self.soft:
            self.soft = 0
            self._log(0x14, 1, 1)
        elif value == 5:
            self._log(0x14, 1, 5)
            self.off = True

    # ---- display interface (same as the real transports)
    def get_vcp_raw(self, code: int):
        if self.off:
            return None
        with self.lock:
            if self.protocol >= 3 and code == 0xD6:
                return (0, 0, 5, 0, 4 if self.soft else 1)
            if self.protocol >= 3 and code == 0xE8:
                manual = self.mem[SETTINGS_BASE - RAM_LO + 0x14F] != 0
                return (0, self.cables, self.soft | (2 if manual else 0), 0x01, 0xFF)
            if code == 0x60:
                return (0, 0, 0x0E, 0, {0: 0x09, 1: 0x06}[self.port])
            if code in self.vcp:
                cur, mx = self.vcp[code]
                return (0, mx >> 8, mx & 0xFF, cur >> 8, cur & 0xFF)
            if code == 0xEA:
                return (0, RING, self.protocol, self.seq >> 8, self.seq & 0xFF)
            if code == 0xEB:
                return (0, 0, 0, self.cursor >> 8, self.cursor & 0xFF)
            if code in (0xEC, 0xED):
                s, eid, old, new, t = self.ring[self.cursor % RING]
                if code == 0xEC:
                    return (0, eid, old, new, s & 0xFF)
                return (0, s & 0xFF, (t >> 16) & 0xFF, (t >> 8) & 0xFF, t & 0xFF)
            if code == 0xEE:
                return (0, self.port, 2 if self.port else 1, 0x41, 1)
            if code == 0xEF:
                t = self.clock()
                return (0, t >> 24, (t >> 16) & 0xFF, (t >> 8) & 0xFF, t & 0xFF)
            if code == 0xF0:
                return (0, 0, 0, (self.addr >> 24) & 0xFF, (self.addr >> 16) & 0xFF)
            if code == 0xF1:
                return (0, 0, 0, (self.addr >> 8) & 0xFF, self.addr & 0xFF)
            if code == 0xF2:
                if not RAM_LO <= self.addr < RAM_HI:
                    return (0, 0xFF, 0xFF, 0xFF, 0xFF)
                o = self.addr - RAM_LO
                b = self.mem[o : o + 4]
                self.addr += 4
                return (0, b[0], b[1], b[2], b[3])
            return (1, 0xFF, 0xFF, 0, 0)  # unsupported, like the stock default case

    def set_vcp(self, code: int, value: int):
        if self.off:
            raise OSError("monitor is off")
        with self.lock:
            if code == 0x60:
                target = {0x09: 0, 0x06: 1}.get(value)
                if target is not None and self.protocol >= 3 and not self.cables & (1 << target):
                    # switch guard: request logged first, then switch-failed at once, and no switch
                    self._log(0x10, self.port, value)
                    self._log(0x12, target, self.port)
                elif target is not None:
                    self._switch(target, value)
            elif code == 0xD6:
                self._set_power(value & 0xFF)
            elif code in self.vcp:
                _, mx = self.vcp[code]
                v = min(value, mx)
                self.vcp[code] = (v, mx)
                if code == 0x10:
                    self._settings_set(0x1D3, v)
                    self._log(0x21, 0xD3, v)
            elif code == 0xEB:
                self.cursor = value & 0xFFFF
            elif code == 0xF0:
                self.addr = (self.addr & 0xFFFF) | ((value & 0xFFFF) << 16)
            elif code == 0xF1:
                self.addr = (self.addr & 0xFFFF0000) | (value & 0xFFFF)
            elif code == 0xF4:
                if SETTINGS_BASE <= self.addr < SETTINGS_BASE + SETTINGS_LEN:
                    off = self.addr - SETTINGS_BASE
                    self._settings_set(off, value)
                    self._log(0x20 | (off >> 8), off & 0xFF, value)
                    self.addr += 1
            elif code == 0xF6:
                pass  # apply menu item: nothing to model beyond accepting it
