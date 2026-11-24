#!/usr/bin/env python3
"""G5 production patch (protocol 3), built in three stages from the stock 1008.3 image.

    p3a  1030.0  Get 0xE8 capability word, Get 0xD6 truthful, Set 0xD6 = 4 or 5 -> stock power off. No RAM used.
    p3b  1031.0  p3a + soft standby: Set 0xD6 = 4 panel off (CPU, link and DDC/CI stay up), 1 = wake, 5 = power off.
    p3c  1032.0  p3b + event ring 0xEA..0xEF, switch verdicts, cable-mask and power-state events, switch guard.

No memory, call or SPI vendor codes: capability bit 6 is 0. The hook only runs when a host sends Get/Set VCP (two
call-site redirects in the DDC/CI dispatcher); the boot path is untouched. Every stock code keeps its handler except
Get 0xEB..0xEF and Set 0xEB in p3c (Samsung service codes, shadowed by the ring). Design, evidence and the HIL
runbook: docs/targets/g5-falcon/tandem-re.md. Guards and addresses: ../versions/1008.3.toml.

The assembler below is a small self-contained SPARC V8 encoder (no keystone/capstone needed), so the builder and its
tests run in the plain workspace environment. Nothing here talks to a monitor.

    uv run python firmware/targets/g5-falcon/patches/production_hook.py \
        data/vendor/g5/stock-1008.3/extracted/"M-C5500GGZA-1008.3[C145].img" --out out/g5
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/mfw/src"))
from mfw import novatek as nv  # noqa: E402

FAMILY = b"M-C5500GGZA"
VERSION_MAP = Path(__file__).resolve().parents[1] / "versions" / "1008.3.toml"
STAGES = {"a": "1030.0", "b": "1031.0", "c": "1032.0"}
CODE_SHIFT = 0x2E000  # file offset = nominal code VA + CODE_SHIFT (the code runs at VA + 0x320; calls are relative)

# Capability bits (docs/protocol/vcp-interface.md, "Protocol 3")
CAP_REAL_INPUT, CAP_VERDICT, CAP_RING, CAP_WAKE = 1 << 0, 1 << 1, 1 << 2, 1 << 3
CAP_CABLE, CAP_SRC_DETECT, CAP_MEMORY, CAP_D6, CAP_GUARD = 1 << 4, 1 << 5, 1 << 6, 1 << 7, 1 << 8
CAPS = {
    "a": CAP_REAL_INPUT | CAP_CABLE | CAP_D6,
    "b": CAP_REAL_INPUT | CAP_CABLE | CAP_D6 | CAP_WAKE,
    "c": CAP_REAL_INPUT | CAP_CABLE | CAP_D6 | CAP_WAKE | CAP_VERDICT | CAP_RING | CAP_GUARD,
}
RING_SIZE = 0x40
PROTOCOL = 3
VERDICT_SECONDS = 8

# RAM layout, relative to RAM_BASE (one sethi). See [ram] in the version map.
RAM_BASE = 0xA803CC00
RING = 0x1C0  # 64 records of 8 bytes: id, old, new, seq low, u32 time (10 ms units)
STATE = 0x3C0
S_MAGIC, S_SOFT, S_PORT, S_SIG, S_CAB, S_PEND, S_SEQ, S_CUR, S_DEAD = 0, 1, 2, 3, 4, 5, 6, 8, 0xC
MAGIC = 0xA5
INITIAL = 0xEE  # "old" value of the first report of each watched value


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------
# SPARC V8 encoder (only what the hook uses)
# ---------------------------------------------------------------------------------------------------------------
_REG = {f"{p}{n}": i * 8 + n for i, p in enumerate("goli") for n in range(8)} | {"sp": 14, "fp": 30}
_ARITH = {
    "add": 0x00, "and": 0x01, "or": 0x02, "xor": 0x03, "sub": 0x04, "subx": 0x0C, "smul": 0x0B, "andcc": 0x11, "subcc": 0x14,
    "sll": 0x25, "srl": 0x26, "jmpl": 0x38, "save": 0x3C, "restore": 0x3D,
}  # fmt: skip
_MEM = {"ld": 0x00, "ldub": 0x01, "lduh": 0x02, "st": 0x04, "stb": 0x05, "sth": 0x06}
_COND = {"ba": 8, "be": 1, "bne": 9, "bleu": 4, "bgu": 0xC, "bneg": 6}


def _src2(v: str | int) -> int:
    if isinstance(v, str):
        return _REG[v]
    if not -4096 <= v <= 4095:
        raise BuildError(f"immediate {v:#x} does not fit simm13")
    return 0x2000 | (v & 0x1FFF)


def _f3(op: int, op3: int, rd: str, rs1: str, src2: str | int) -> int:
    return (op << 30) | (_REG[rd] << 25) | (op3 << 19) | (_REG[rs1] << 14) | _src2(src2)


@dataclass
class Asm:
    """Two-pass assembler over named sections. Labels are global; branch and call targets may be absolute VAs."""

    sections: dict[str, tuple[int, int]]  # name -> (base VA, size in bytes)
    _items: dict[str, list[tuple]] = field(default_factory=dict)
    _cur: str = ""
    labels: dict[str, int] = field(default_factory=dict)

    def org(self, name: str) -> None:
        self._cur = name
        self._items.setdefault(name, [])

    def label(self, name: str) -> None:
        self._items[self._cur].append(("label", name))

    def _emit(self, *item) -> None:
        self._items[self._cur].append(item)

    def op(self, name: str, rs1: str, src2: str | int, rd: str) -> None:
        self._emit("word", _f3(2, _ARITH[name], rd, rs1, src2))

    def mov(self, src: str | int, rd: str) -> None:
        self.op("or", "g0", src, rd)

    def cmp(self, rs1: str, src2: str | int) -> None:
        self.op("subcc", rs1, src2, "g0")

    def load(self, name: str, base: str, off: str | int, rd: str) -> None:
        self._emit("word", _f3(3, _MEM[name], rd, base, off))

    def store(self, name: str, rs: str, base: str, off: str | int) -> None:
        self._emit("word", _f3(3, _MEM[name], rs, base, off))

    def sethi(self, value: int, rd: str) -> None:
        """rd = value with the low 10 bits cleared (value must be a multiple of 0x400 unless followed by an or)."""
        self._emit("word", (_REG[rd] << 25) | (4 << 22) | ((value >> 10) & 0x3FFFFF))

    def set(self, value: int, rd: str) -> None:
        self.sethi(value, rd)
        if value & 0x3FF:
            self.op("or", rd, value & 0x3FF, rd)

    def nop(self) -> None:
        self._emit("word", 0x01000000)

    def b(self, cond: str, target: str | int, annul: bool = False) -> None:
        self._emit("branch", cond, annul, target)

    def call(self, target: str | int) -> None:
        self._emit("call", target)

    def ret_restore(self, value: int) -> None:
        """ret ; restore %g0, value, %o0 (return *value* to the caller of the windowed routine)."""
        self.op("jmpl", "i7", 8, "g0")
        self.op("restore", "g0", value, "o0")

    def retl(self) -> None:
        self.op("jmpl", "o7", 8, "g0")

    def assemble(self) -> dict[str, bytes]:
        for name, items in self._items.items():
            pc = self.sections[name][0]
            for it in items:
                if it[0] == "label":
                    if it[1] in self.labels:
                        raise BuildError(f"duplicate label {it[1]}")
                    self.labels[it[1]] = pc
                else:
                    pc += 4
        out: dict[str, bytes] = {}
        for name, items in self._items.items():
            base, size = self.sections[name]
            pc, words = base, []
            for it in items:
                if it[0] == "label":
                    continue
                if it[0] == "word":
                    words.append(it[1])
                else:
                    target = self.labels[it[-1]] if isinstance(it[-1], str) else it[-1]
                    disp = target - pc
                    if disp % 4:
                        raise BuildError("unaligned branch target")
                    if it[0] == "call":
                        words.append(0x40000000 | ((disp >> 2) & 0x3FFFFFFF))
                    else:
                        if not -(1 << 23) <= disp < (1 << 23):
                            raise BuildError("branch out of range")
                        words.append((int(it[2]) << 29) | (_COND[it[1]] << 25) | (2 << 22) | ((disp >> 2) & 0x3FFFFF))
                pc += 4
            code = b"".join(struct.pack(">I", w) for w in words)
            if len(code) > size:
                raise BuildError(f"section {name}: {len(code):#x} bytes do not fit {size:#x}")
            out[name] = code
        return out


# ---------------------------------------------------------------------------------------------------------------
# Version map (addresses and guards)
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class VersionMap:
    image_sha256: str
    image_size: int
    sym: dict[str, int]
    ram: dict[str, int]
    regions: dict[str, tuple[int, int]]
    guards: list[dict]

    @staticmethod
    def load(path: Path = VERSION_MAP) -> VersionMap:
        t = tomllib.loads(path.read_text())
        regions = {k: (v["start"], v["size"]) for k, v in t["production"]["regions"].items()}
        return VersionMap(
            t["version"]["image_sha256"],
            t["version"]["image_size"],
            t["production"]["symbols"],
            t["production"]["ram"],
            regions,
            t["guards"],
        )


def check_base(image: bytes, vm: VersionMap) -> None:
    """Refuse anything that is not the exact stock image the addresses were verified against."""
    if len(image) != vm.image_size:
        raise BuildError(f"base image is {len(image)} bytes, expected {vm.image_size}")
    if hashlib.sha256(image).hexdigest() != vm.image_sha256:
        raise BuildError("base image is not stock 1008.3 (sha256 mismatch)")
    for g in vm.guards:
        got = hashlib.sha256(image[g["at"] : g["at"] + g["len"]]).hexdigest()
        if got != g["expect_sha256"]:
            raise BuildError(f"guard {g['name']} failed at file {g['at']:#x}")


# ---------------------------------------------------------------------------------------------------------------
# The hook
# ---------------------------------------------------------------------------------------------------------------
def build_hook(stage: str, vm: VersionMap) -> tuple[Asm, dict[str, bytes]]:
    if stage not in STAGES:
        raise BuildError(f"unknown stage {stage!r}")
    s, ram = vm.sym, vm.ram
    if (ram["base"], ram["ring"] - ram["base"], ram["state"] - ram["base"]) != (RAM_BASE, RING, STATE):
        raise BuildError("version map RAM layout does not match the builder")
    ring, soft = stage == "c", stage in "bc"
    a = Asm(vm.regions)
    st = lambda off: STATE + off  # noqa: E731  (state field displacement from %l7)

    # ---- section "main": Get and Set entries (reached by the two redirected calls of the dispatcher) ----
    a.org("main")
    a.label("GET")  # %o0 = VCP code, %o1 = reply buffer ([0]=CL [1]=ML [2]=CH [3]=MH), %o7 = call site
    if ring:
        a.cmp("o0", 0xD6)
        a.b("be", "GSAVE")
        a.op("sub", "o0", 0xE8, "g1")
        a.cmp("g1", 7)
        a.b("bgu", s["get_vcp"])
        a.cmp("g1", 1)  # 0xE8..0xEF are ours, except 0xE9 (stock)
        a.b("be", s["get_vcp"])
        a.nop()
    else:
        a.cmp("o0", 0xE8)
        a.b("be", "GSAVE")
        a.cmp("o0", 0xD6)
        a.b("be", "GSAVE")
        a.nop()
        a.b("ba", s["get_vcp"])
        a.nop()
    a.label("GSAVE")
    a.op("save", "sp", -0x60, "sp")
    if soft:
        a.sethi(RAM_BASE, "l7")
        a.call("INIT")
        a.nop()
        a.cmp("o0", 0)
        a.b("be", "GPASS")
        a.nop()
    a.cmp("i0", 0xD6)
    a.b("be", "GD6")
    a.nop()
    if ring:
        a.cmp("i0", 0xE8)
        a.b("bne", "GRING")
        a.nop()
    # Get 0xE8: MH = cable mask, ML = flags (bit0 soft standby), CH:CL = capability bits
    a.call("CABMASK")
    a.nop()
    a.op("sll", "o0", 24, "l0")
    if soft:
        a.load("ldub", "l7", st(S_SOFT), "g1")
        a.op("sll", "g1", 16, "g1")
        a.op("or", "l0", "g1", "l0")
    a.b("ba", "GOUT")
    a.op("or", "l0", CAPS[stage], "l0")
    a.label("GD6")  # MH:ML = 0x0005, CL = 1 on / 4 soft standby
    a.sethi(0x00050000, "l0")
    if soft:
        a.load("ldub", "l7", st(S_SOFT), "g1")
        a.op("sll", "g1", 1, "g2")
        a.op("add", "g1", "g2", "g1")
        a.op("add", "g1", 1, "g1")
        a.b("ba", "GOUT")
        a.op("or", "l0", "g1", "l0")
    else:
        a.b("ba", "GOUT")
        a.op("or", "l0", 1, "l0")
    if ring:
        a.org("aux")  # ring reads live in their own region; every path ends with a branch back to GOUT
        a.label("GRING")
        a.cmp("i0", 0xEA)
        a.b("bne", "G_EB")
        a.nop()
        a.call("SAMPLE")
        a.nop()  # the host's poll is what advances the watchers
        a.load("lduh", "l7", st(S_SEQ), "l0")
        a.sethi((RING_SIZE << 24) | (PROTOCOL << 16), "g1")
        a.b("ba", "GOUT")
        a.op("or", "l0", "g1", "l0")
        a.label("G_EB")
        a.cmp("i0", 0xEB)
        a.b("bne", "G_EE")
        a.nop()
        a.b("ba", "GOUT")
        a.load("lduh", "l7", st(S_CUR), "l0")
        a.label("G_EE")
        a.cmp("i0", 0xEE)
        a.b("be", "GEE")
        a.cmp("i0", 0xEF)
        a.b("be", "GEF")
        a.nop()
        # 0xEC / 0xED: the record at the cursor
        a.load("lduh", "l7", st(S_CUR), "g1")
        a.op("and", "g1", RING_SIZE - 1, "g1")
        a.op("sll", "g1", 3, "g1")
        a.op("add", "g1", "l7", "g1")
        a.load("ld", "g1", RING, "l0")  # id, old, new, seq low = MH ML CH CL
        a.cmp("i0", 0xEC)
        a.b("be", "GOUT")
        a.nop()
        a.load("ld", "g1", RING + 4, "g2")
        a.op("sll", "l0", 24, "l0")  # 0xED: MH = seq low, then 24-bit time
        a.op("sll", "g2", 8, "g2")
        a.op("srl", "g2", 8, "g2")
        a.b("ba", "GOUT")
        a.op("or", "l0", "g2", "l0")
        a.label("GEE")  # live: MH = port, ML = 0, CH = power flags (bit0 on), CL = picture locked
        a.call("SAMPLE")
        a.nop()
        a.load("ldub", "l7", st(S_PORT), "l0")
        a.op("sll", "l0", 24, "l0")
        a.load("ldub", "l7", st(S_SIG), "g1")
        a.op("or", "l0", "g1", "l0")
        a.b("ba", "GOUT")
        a.op("or", "l0", 0x100, "l0")
        a.label("GEF")  # clock: 10 ms units (the firmware tick is in seconds)
        a.sethi(s["tick_seconds"], "g1")
        a.load("ld", "g1", s["tick_seconds"] & 0x3FF, "l0")
        a.b("ba", "GOUT")
        a.op("smul", "l0", 100, "l0")
        a.org("main")
    a.label("GOUT")  # %l0 = MH ML CH CL
    a.op("srl", "l0", 24, "g1")
    a.store("stb", "g1", "i1", 3)
    a.op("srl", "l0", 16, "g1")
    a.store("stb", "g1", "i1", 1)
    a.op("srl", "l0", 8, "g1")
    a.store("stb", "g1", "i1", 2)
    a.store("stb", "l0", "i1", 0)
    a.ret_restore(1)
    if soft:
        a.label("GPASS")
        a.b("ba", s["get_vcp"])
        a.op("restore", "g0", "g0", "g0")

    a.label("SET")  # %o0 = VCP code, %o1 = packet pointer (value high at +3, low at +4), %o7 = call site
    a.cmp("o0", 0xD6)
    a.b("be", "SSAVE")
    if ring:
        a.cmp("o0", 0x60)
        a.b("be", "SSAVE")
        a.cmp("o0", 0xEB)
        a.b("be", "SSAVE")
    a.nop()
    a.b("ba", s["set_vcp"])
    a.nop()
    a.label("SSAVE")
    a.op("save", "sp", -0x60, "sp")
    if soft:
        a.sethi(RAM_BASE, "l7")
        a.call("INIT")
        a.nop()
        a.cmp("o0", 0)
        a.b("be", "SPASS")
        a.nop()
    a.load("ldub", "i1", 4, "l1")  # value low byte
    if ring:
        a.cmp("i0", 0x60)
        a.b("be", "S60")
        a.cmp("i0", 0xEB)
        a.b("be", "SEB")
        a.nop()
    # Set 0xD6
    if not soft:
        a.cmp("l1", 4)
        a.b("be", "SOFF")
        a.cmp("l1", 5)
        a.b("bne", "SPASS")
        a.nop()
    else:
        a.cmp("l1", 5)
        a.b("be", "SOFF")
        a.cmp("l1", 4)
        a.b("be", "SSOFT")
        a.cmp("l1", 1)
        a.b("bne", "SPASS")
        a.nop()
        # 1 = wake from soft standby
        a.load("ldub", "l7", st(S_SOFT), "g1")
        a.cmp("g1", 0)
        a.b("be", "SEVENT")
        a.nop()
        a.mov(1, "o0")
        a.call(s["panel_on_off"])
        a.mov(1, "o1")
        a.call(s["led_power_on"])
        a.nop()
        a.b("ba", "SEVENT")
        a.store("stb", "g0", "l7", st(S_SOFT))
        a.label("SSOFT")  # 4 = soft standby: panel sequence off, LED to its off state, everything else keeps running
        a.load("ldub", "l7", st(S_SOFT), "g1")
        a.cmp("g1", 0)
        a.b("bne", "SEVENT")
        a.nop()
        a.mov(0, "o0")
        a.call(s["panel_on_off"])
        a.mov(1, "o1")
        a.call(s["led_power_off"])
        a.nop()
        a.mov(1, "g1")
        a.store("stb", "g1", "l7", st(S_SOFT))
        a.label("SEVENT")
        if ring:
            a.mov(0x14, "o0")
            a.mov(1, "o1")
            a.call("PUSH")
            a.mov("l1", "o2")  # power-state: cause DDC
        a.b("ba", "SRET")
        a.nop()
    a.label("SOFF")  # stock power off, the same call the off timer makes from this main-loop context
    if ring:
        a.mov(0x14, "o0")
        a.mov(1, "o1")
        a.call("PUSH")
        a.mov(5, "o2")
    if soft:
        a.store("stb", "g0", "l7", st(S_SOFT))
    a.call(s["set_power_state"])
    a.mov(1, "o0")
    if ring:
        a.org("aux")
        a.label("S60")
        a.call("SAMPLE")
        a.nop()
        a.load("ldub", "l7", st(S_PORT), "o1")
        a.mov("l1", "o2")
        a.call("PUSH")
        a.mov(0x10, "o0")
        a.cmp("l1", 0x0F)
        a.b("be", "S60T")
        a.mov(0, "l2")  # 0x0F = DP -> port 0
        a.cmp("l1", 0x11)
        a.b("bne", "SPASS")
        a.mov(1, "l2")  # 0x11 = HDMI -> port 1; others: stock decides
        a.label("S60T")
        a.call("CABMASK")
        a.nop()
        a.op("srl", "o0", "l2", "o0")
        a.op("andcc", "o0", 1, "g0")
        a.b("bne", "S60GO")
        a.nop()
        a.mov("l2", "o1")
        a.load("ldub", "l7", st(S_PORT), "o2")
        a.call("PUSH")
        a.mov(0x12, "o0")  # guard
        a.b("ba", "SRET")
        a.nop()
        a.org("sample")
        a.label("S60GO")
        a.op("add", "l2", 1, "g1")
        a.store("stb", "g1", "l7", st(S_PEND))
        a.sethi(s["tick_seconds"], "g1")
        a.load("ld", "g1", s["tick_seconds"] & 0x3FF, "g1")
        a.op("add", "g1", VERDICT_SECONDS, "g1")
        a.b("ba", "SPASS")
        a.store("st", "g1", "l7", st(S_DEAD))
        a.label("SEB")
        a.load("ldub", "i1", 3, "g1")
        a.op("sll", "g1", 8, "g1")
        a.op("or", "g1", "l1", "g1")  # cursor = value16
        a.b("ba", "SRET")
        a.store("sth", "g1", "l7", st(S_CUR))
        a.org("main")
    a.label("SRET")
    a.ret_restore(1)
    a.label("SPASS")
    a.b("ba", s["set_vcp"])
    a.op("restore", "g0", "g0", "g0")

    if soft:
        a.label("INIT")  # leaf. %o0 = 0 when the RAM block is not ours to use, else 1 (state initialised once per boot)
        a.sethi(s["heap_break"], "g1")
        a.load("ld", "g1", s["heap_break"] & 0x3FF, "g1")
        a.set(RAM_BASE + RING, "g2")
        a.cmp("g1", "g2")
        a.b("bgu", "IRET")
        a.mov(0, "o0")
        a.load("ldub", "l7", st(S_MAGIC), "g1")
        a.cmp("g1", MAGIC)
        a.b("be", "IRET")
        a.mov(1, "o0")
        for off in (0, 4, 8, 0xC):
            a.store("st", "g0", "l7", st(off))
        a.mov(MAGIC, "g1")
        a.store("stb", "g1", "l7", st(S_MAGIC))
        if ring:
            a.mov(INITIAL, "g1")
            for off in (S_PORT, S_SIG, S_CAB):
                a.store("stb", "g1", "l7", st(off))
            a.mov("o7", "g4")
            a.mov(0, "o0")
            a.mov(0, "o1")
            a.call("PUSH")
            a.mov(0, "o2")  # boot event
            a.mov("g4", "o7")
            a.mov(1, "o0")
        a.label("IRET")
        a.retl()
        a.nop()

    # ---- section "leaf": small leaf routines ----
    a.org("leaf")
    a.label("CABMASK")  # %o0 = bit0 DP cable, bit1 HDMI cable (the firmware's own cable-state table: 2 = connected)
    a.sethi(s["cable_state"], "g1")
    a.load("ld", "g1", (s["cable_state"] & 0x3FF) + 4, "g2")
    a.load("ld", "g1", s["cable_state"] & 0x3FF, "g3")
    a.op("xor", "g2", 2, "g2")
    a.cmp("g0", "g2")
    a.op("subx", "g0", -1, "o0")
    a.op("xor", "g3", 2, "g3")
    a.cmp("g0", "g3")
    a.op("subx", "g0", -1, "g3")
    a.op("sll", "g3", 1, "g3")
    a.retl()
    a.op("or", "o0", "g3", "o0")
    if ring:
        a.label("CHANGED")  # %o0 = id, %o2 = new value, %o3 = state displacement: log only when the value changed
        a.load("ldub", "l7", "o3", "o1")
        a.cmp("o1", "o2")
        a.b("bne", "PUSH", annul=True)
        a.store("stb", "o2", "l7", "o3")
        a.retl()
        a.nop()
        a.label("PUSH")  # %o0 = id, %o1 = old, %o2 = new. Uses %g1..%g3, needs %l7 = RAM_BASE
        a.load("lduh", "l7", st(S_SEQ), "g1")
        a.op("add", "g1", 1, "g1")
        a.store("sth", "g1", "l7", st(S_SEQ))
        a.op("and", "g1", RING_SIZE - 1, "g2")
        a.op("sll", "g2", 3, "g2")
        a.op("add", "g2", "l7", "g2")
        a.store("stb", "o0", "g2", RING)
        a.store("stb", "o1", "g2", RING + 1)
        a.store("stb", "o2", "g2", RING + 2)
        a.store("stb", "g1", "g2", RING + 3)
        a.sethi(s["tick_seconds"], "g3")
        a.load("ld", "g3", s["tick_seconds"] & 0x3FF, "g3")
        a.op("smul", "g3", 100, "g3")
        a.retl()
        a.store("st", "g3", "g2", RING + 4)

        # ---- section "sample": watchers and the switch verdict (p3c only) ----
        a.org("sample")
        a.label("SAMPLE")  # runs in the caller's window: uses %l3..%l6, %o0..%o3, %g1..%g3
        a.mov("o7", "l6")
        a.call(s["get_current_source"])
        a.mov(0, "o0")  # 0x10 = DP1, 0x00 = HDMI1 (same call as stock Get 0x60)
        a.op("srl", "o0", 4, "l3")
        a.op("xor", "l3", 1, "l3")
        a.op("and", "l3", 1, "l3")  # port: 0 DP, 1 HDMI
        a.mov(0x01, "o0")
        a.mov("l3", "o2")
        a.call("CHANGED")
        a.mov(st(S_PORT), "o3")
        a.sethi(s["sync_state"], "g1")
        a.load("ld", "g1", s["sync_state"] & 0x3FF, "g1")
        a.op("xor", "g1", s["sync_locked"], "g1")
        a.cmp("g0", "g1")
        a.op("subx", "g0", -1, "l4")  # 1 = locked
        a.mov(0x06, "o0")
        a.mov("l4", "o2")
        a.call("CHANGED")
        a.mov(st(S_SIG), "o3")
        a.call("CABMASK")
        a.nop()
        a.mov("o0", "o2")
        a.mov(0x15, "o0")
        a.call("CHANGED")
        a.mov(st(S_CAB), "o3")
        a.load("ldub", "l7", st(S_PEND), "g1")
        a.op("subcc", "g1", 1, "o1")
        a.b("bneg", "SDONE")
        a.nop()
        a.cmp("o1", "l3")
        a.b("bne", "SWAIT")
        a.nop()  # %o1 = target port of the pending switch
        a.cmp("l4", 0)
        a.b("bne", "SOK")
        a.nop()
        a.label("SWAIT")  # pending while (deadline - now) <= VERDICT_SECONDS, unsigned (also ends on a tick wrap)
        a.sethi(s["tick_seconds"], "g1")
        a.load("ld", "g1", s["tick_seconds"] & 0x3FF, "g1")
        a.load("ld", "l7", st(S_DEAD), "g2")
        a.op("sub", "g2", "g1", "g1")
        a.cmp("g1", VERDICT_SECONDS)
        a.b("bleu", "SDONE")
        a.nop()
        a.mov("l3", "o2")
        a.b("ba", "SVERDICT")
        a.mov(0x12, "o0")  # switch-failed: old = target, new = current
        a.label("SOK")
        a.mov("o1", "o2")
        a.mov(0x11, "o0")  # switch-done: old = new = target
        a.label("SVERDICT")
        a.call("PUSH")
        a.store("stb", "g0", "l7", st(S_PEND))
        a.label("SDONE")
        a.op("jmpl", "l6", 8, "g0")
        a.nop()
    return a, a.assemble()


# ---------------------------------------------------------------------------------------------------------------
# Image assembly
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Built:
    stage: str
    image: bytes
    name: nv.ImageName
    sizes: dict[str, int]
    labels: dict[str, int]


def _call_word(pc: int, target: int) -> bytes:
    return struct.pack(">I", 0x40000000 | (((target - pc) >> 2) & 0x3FFFFFFF))


def build(stock: bytes, stage: str | None, vm: VersionMap | None = None) -> Built:
    """Return the image for *stage* ("a", "b", "c"); None returns the stock image unchanged (round trip)."""
    vm = vm or VersionMap.load()
    check_base(stock, vm)
    if stage is None:
        info = nv.identify(stock, FAMILY)
        return Built("stock", stock, nv.ImageName(info.embedded.family, info.embedded.version, info.tag), {}, {})
    asm, code = build_hook(stage, vm)
    d = bytearray(stock)
    for name, blob in code.items():
        base = vm.regions[name][0]
        d[base + CODE_SHIFT : base + CODE_SHIFT + len(blob)] = blob
    for site, entry in ((vm.sym["get_call_site"], "GET"), (vm.sym["set_call_site"], "SET")):
        d[site + CODE_SHIFT : site + CODE_SHIFT + 4] = _call_word(site, asm.labels[entry])
    out, name = nv.restamp(bytes(d), STAGES[stage], family=FAMILY)
    nv.verify_stock(out, name.filename, family=FAMILY)
    return Built(stage, out, name, {k: len(v) for k, v in code.items()}, dict(asm.labels))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock", type=Path, help="the stock M-C5500GGZA-1008.3[C145].img (your own copy)")
    ap.add_argument("--out", type=Path, default=Path("out/g5"), help="output directory (gitignored)")
    ap.add_argument("--stage", choices=[*STAGES, "all"], default="all")
    args = ap.parse_args(argv)
    stock = args.stock.read_bytes()
    vm = VersionMap.load()
    args.out.mkdir(parents=True, exist_ok=True)
    for stage in STAGES if args.stage == "all" else [args.stage]:
        b = build(stock, stage, vm)
        path = args.out / b.name.filename
        path.write_bytes(b.image)
        changed = sum(1 for x, y in zip(stock, b.image, strict=True) if x != y)
        used = ", ".join(f"{k} {v:#x}/{vm.regions[k][1]:#x}" for k, v in b.sizes.items())
        print(f"p3{stage}: {path}  sha256 {hashlib.sha256(b.image).hexdigest()}  ({changed} bytes changed; {used})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
