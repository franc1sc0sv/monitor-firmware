"""G5 production hook (protocol 3): builder checks and a behavioural run of the generated machine code.

The hook is executed by a tiny SPARC V8 interpreter written here independently of the builder's encoder, with the
firmware routines it calls replaced by stubs (a "FakeMonitor" at instruction level). Nothing needs hardware. Tests
that need the user's own stock image are skipped when it is not present (it is never in the repository).
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "firmware/targets/g5-falcon/patches/production_hook.py"
STOCK = ROOT / "data/vendor/g5/stock-1008.3/extracted/M-C5500GGZA-1008.3[C145].img"

_spec = importlib.util.spec_from_file_location("g5_production_hook", BUILDER)
assert _spec and _spec.loader
ph = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ph
_spec.loader.exec_module(ph)

VM = ph.VersionMap.load()
SYM = VM.sym
GET_CS, SET_CS = SYM["get_call_site"], SYM["set_call_site"]
BUF, PKT, STACK = 0x70000100, 0x70000201, 0x70008000
M32 = 0xFFFFFFFF


class Machine:
    """SPARC V8 subset interpreter with register windows, delay slots and annulled branches."""

    def __init__(self, stage: str):
        self.stage = stage
        asm, code = ph.build_hook(stage, VM)
        self.labels = asm.labels
        self.mem: dict[int, int] = {}
        self.code: dict[int, int] = {}
        for name, blob in code.items():
            base = VM.regions[name][0]
            for k in range(0, len(blob), 4):
                self.code[base + k] = struct.unpack(">I", blob[k : k + 4])[0]
        self.g = [0] * 8
        self.wins = [{"o": [0] * 8, "l": [0] * 8, "i": [0] * 8}]
        self.n = self.z = self.c = 0
        self.log: list[tuple] = []
        self.source = 0x10  # DP1
        self.w32(SYM["sync_state"], SYM["sync_locked"])
        self.w32(SYM["cable_state"], 2)  # HDMI connected
        self.w32(SYM["cable_state"] + 4, 2)  # DP connected
        self.w32(SYM["tick_seconds"], 100)

    # -- memory --
    def w8(self, a: int, v: int) -> None:
        self.mem[a] = v & 0xFF

    def r8(self, a: int) -> int:
        return self.mem.get(a, 0)

    def w32(self, a: int, v: int) -> None:
        assert a % 4 == 0, f"unaligned word store at {a:#x}"
        for k in range(4):
            self.w8(a + k, v >> (24 - 8 * k))

    def r32(self, a: int) -> int:
        assert a % 4 == 0, f"unaligned word load at {a:#x}"
        return int.from_bytes(bytes(self.r8(a + k) for k in range(4)), "big")

    # -- registers --
    def rd(self, r: int) -> int:
        w = self.wins[-1]
        return (
            0
            if r == 0
            else self.g[r]
            if r < 8
            else w["o"][r - 8]
            if r < 16
            else w["l"][r - 16]
            if r < 24
            else w["i"][r - 24]
        )

    def wr(self, r: int, v: int) -> None:
        v &= M32
        w = self.wins[-1]
        if r == 0:
            return
        if r < 8:
            self.g[r] = v
        elif r < 16:
            w["o"][r - 8] = v
        elif r < 24:
            w["l"][r - 16] = v
        else:
            w["i"][r - 24] = v

    # -- firmware stubs: return like a windowed callee (caller's %o1..%o5 and %g1..%g4 are not preserved) --
    def stub(self, pc: int) -> bool:
        names = {SYM[k]: k for k in ("get_vcp", "set_vcp", "get_current_source", "set_power_state", "panel_on_off",
                                     "led_power_on", "led_power_off")}  # fmt: skip
        if pc not in names:
            return False
        name, o = names[pc], self.wins[-1]["o"]
        ret = 0
        if name in ("get_vcp", "set_vcp"):
            assert len(self.wins) == 1, "pass-through must happen in the dispatcher's own window"
            self.log.append((name, o[0]))
        elif name == "get_current_source":
            assert o[0] == 0
            ret = self.source
        elif name == "panel_on_off":
            self.log.append((name, o[0], o[1]))
        else:
            self.log.append((name, o[0]) if name == "set_power_state" else (name,))
        for k in range(1, 6):
            o[k] = 0xDEAD0000 + k
        for k in range(1, 5):
            self.g[k] = 0xBEEF0000 + k
        o[0] = ret
        return True

    def call(self, entry: str, site: int, o0: int, o1: int) -> int:
        o = self.wins[-1]["o"]
        o[0], o[1], o[2], o[6], o[7] = o0, o1, 0x77, STACK, site
        self.wins[-1]["l"] = [0x1111 * k for k in range(8)]
        keep = list(self.wins[-1]["l"])
        pc, npc = self.labels[entry], self.labels[entry] + 4
        for _ in range(5000):
            if pc == site + 8:
                assert len(self.wins) == 1 and self.wins[-1]["l"] == keep, "caller's window was disturbed"
                return o[0]
            if self.stub(pc):
                pc = self.rd(15) + 8
                npc = pc + 4
                continue
            pc, npc = self.step(pc, npc)
        raise AssertionError("hook did not return")

    def step(self, pc: int, npc: int) -> tuple[int, int]:
        w = self.code[pc]  # KeyError = execution left the hook without reaching a stub or the call site
        op, rd, op3, rs1 = w >> 30, (w >> 25) & 31, (w >> 19) & 0x3F, (w >> 14) & 31
        simm = (w & 0x1FFF) - (0x2000 if w & 0x1000 else 0)
        src2 = simm if w & 0x2000 else self.rd(w & 31)
        nnpc = npc + 4
        if op == 1:
            disp = (w & 0x3FFFFFFF) - (1 << 30 if w & (1 << 29) else 0)
            self.wr(15, pc)
            return npc, pc + 4 * disp
        if op == 0:
            op2 = (w >> 22) & 7
            if op2 == 4:
                self.wr(rd, (w & 0x3FFFFF) << 10)
                return npc, nnpc
            assert op2 == 2, f"unknown op at {pc:#x}"
            cond, annul = (w >> 25) & 15, (w >> 29) & 1
            disp = (w & 0x3FFFFF) - (1 << 22 if w & (1 << 21) else 0)
            taken = {8: True, 1: self.z == 1, 9: self.z == 0, 4: bool(self.c or self.z), 0xC: not (self.c or self.z),
                     6: self.n == 1}[cond]  # fmt: skip
            if taken:
                assert not (annul and cond == 8), "ba,a is not used"
                return npc, pc + 4 * disp
            return (nnpc, nnpc + 4) if annul else (npc, nnpc)
        a = self.rd(rs1)
        if op == 3:
            addr = (a + src2) & M32
            if op3 == 0:
                self.wr(rd, self.r32(addr))
            elif op3 == 1:
                self.wr(rd, self.r8(addr))
            elif op3 == 2:
                assert addr % 2 == 0
                self.wr(rd, self.r8(addr) << 8 | self.r8(addr + 1))
            elif op3 == 4:
                self.w32(addr, self.rd(rd))
            elif op3 == 5:
                self.w8(addr, self.rd(rd))
            elif op3 == 6:
                assert addr % 2 == 0
                self.w8(addr, self.rd(rd) >> 8)
                self.w8(addr + 1, self.rd(rd))
            else:
                raise AssertionError(f"unknown memory op at {pc:#x}")
            return npc, nnpc
        b = src2 & M32
        if op3 in (0x04, 0x14, 0x0C):  # sub, subcc, subx
            r = a - b - (self.c if op3 == 0x0C else 0)
            if op3 == 0x14:
                self.c, self.z, self.n = int(a < b), int(r & M32 == 0), (r >> 31) & 1
            self.wr(rd, r)
        elif op3 in (0x01, 0x11):
            r = a & b
            if op3 == 0x11:
                self.c, self.z, self.n = 0, int(r == 0), (r >> 31) & 1
            self.wr(rd, r)
        elif op3 == 0x00:
            self.wr(rd, a + b)
        elif op3 == 0x02:
            self.wr(rd, a | b)
        elif op3 == 0x03:
            self.wr(rd, a ^ b)
        elif op3 == 0x0B:
            self.wr(rd, a * b)
        elif op3 == 0x25:
            self.wr(rd, a << (b & 31))
        elif op3 == 0x26:
            self.wr(rd, a >> (b & 31))
        elif op3 == 0x38:  # jmpl
            self.wr(rd, pc)
            return npc, (a + src2) & M32
        elif op3 == 0x3C:  # save
            old = self.wins[-1]
            self.wins.append({"o": [0] * 8, "l": [0xAAAA0000 + k for k in range(8)], "i": old["o"]})
            self.wr(rd, a + src2)
        elif op3 == 0x3D:  # restore
            r = a + src2
            self.wins.pop()
            self.wr(rd, r)
        else:
            raise AssertionError(f"unknown op3 {op3:#x} at {pc:#x}")
        return npc, nnpc

    # -- the DDC/CI view --
    def get(self, code: int) -> tuple[int, int, int, int] | None:
        for k in range(4):
            self.w8(BUF + k, 0)
        if self.call("GET", GET_CS, code, BUF) == 0:
            return None  # stock answered (the stub says "unsupported")
        return self.r8(BUF + 3), self.r8(BUF + 1), self.r8(BUF + 2), self.r8(BUF)  # MH ML CH CL

    def set(self, code: int, value: int) -> bool:
        self.w8(PKT + 3, value >> 8)
        self.w8(PKT + 4, value)
        return self.call("SET", SET_CS, code, PKT) == 1

    def events(self) -> list[tuple[int, int, int]]:
        """Drain the ring the way the Rust StandardMonitor does: 0xEA, then cursor / 0xEC / 0xED per record."""
        head = self.get(0xEA)
        assert head and head[0] == 0x40 and head[1] == 3
        newest, out = head[2] << 8 | head[3], []
        while self.cursor != newest:
            self.cursor = (self.cursor + 1) & 0xFFFF
            assert self.set(0xEB, self.cursor)
            rec, tim = self.get(0xEC), self.get(0xED)
            assert rec and tim and rec[3] == tim[0] == self.cursor & 0xFF
            out.append(rec[:3])
        return out

    cursor = 0


@pytest.fixture(params=["a", "b", "c"])
def any_stage(request) -> Machine:
    return Machine(request.param)


def stock_image() -> bytes:
    if not STOCK.exists():
        pytest.skip("stock 1008.3 image not present (data/ is local only)")
    return STOCK.read_bytes()


# ---- builder ----
def test_sections_fit_and_stay_in_their_regions():
    for stage in ph.STAGES:
        asm, code = ph.build_hook(stage, VM)
        for name, blob in code.items():
            assert len(blob) <= VM.regions[name][1] and len(blob) % 4 == 0
        used = set(code)
        assert used <= ({"main", "leaf"} if stage != "c" else {"main", "leaf", "aux", "sample"})
        spans = [(VM.regions[n][0], VM.regions[n][0] + VM.regions[n][1]) for n in VM.regions]
        assert all(any(lo <= v < hi for lo, hi in spans) for v in asm.labels.values())


def test_regions_and_guards_cover_every_patch_site():
    guarded = [(g["at"], g["at"] + g["len"]) for g in VM.guards]
    sites = [(GET_CS + ph.CODE_SHIFT, 4), (SET_CS + ph.CODE_SHIFT, 4)]
    sites += [(start + ph.CODE_SHIFT, size) for start, size in VM.regions.values()]
    for at, size in sites:
        assert any(lo <= at and at + size <= hi for lo, hi in guarded), f"no guard covers file {at:#x}"
    spans = sorted(VM.regions.values())
    assert all(a[0] + a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False)), "regions overlap"


def test_ram_block_is_inside_the_guarded_window():
    assert VM.ram["ring"] + 8 * ph.RING_SIZE == VM.ram["state"]
    assert VM.ram["ring"] > SYM["heap_break"] and VM.ram["state"] + 0x10 <= 0xA803D000


def test_wrong_base_image_is_refused():
    with pytest.raises(ph.BuildError):
        ph.build(b"\x00" * VM.image_size, "a", VM)
    with pytest.raises(ph.BuildError):
        ph.build(b"\x7fNVTSC_IMG\n" + b"\x00" * 64, None, VM)


def test_each_guard_refuses_a_changed_site():
    stock = stock_image()
    for g in VM.guards:
        bad = bytearray(stock)
        bad[g["at"]] ^= 0xFF
        vm = dataclasses.replace(VM, image_sha256=hashlib.sha256(bad).hexdigest())
        with pytest.raises(ph.BuildError, match=g["name"]):
            ph.build(bytes(bad), "c", vm)


def test_no_stage_returns_the_stock_image_unchanged():
    stock = stock_image()
    b = ph.build(stock, None, VM)
    assert b.image == stock and b.name.filename == STOCK.name


def test_images_are_stamped_checksummed_and_change_only_the_patch_sites():
    stock = stock_image()
    allowed = [(GET_CS + ph.CODE_SHIFT, 4), (SET_CS + ph.CODE_SHIFT, 4), (0x273364, 6)]
    allowed += [(start + ph.CODE_SHIFT, size) for start, size in VM.regions.values()]
    seen = set()
    for stage, version in ph.STAGES.items():
        b = ph.build(stock, stage, VM)
        assert len(b.image) == len(stock) and b.name.version == version
        assert ph.nv.verify_stock(b.image, b.name.filename, family=ph.FAMILY).embedded.version == version
        assert ph.nv.parse_filename(b.name.filename).tag == ph.nv.tag(b.image)
        diff = [i for i, (x, y) in enumerate(zip(stock, b.image, strict=True)) if x != y]
        assert all(any(at <= i < at + size for at, size in allowed) for i in diff)
        assert min(diff) >= 0x2DCE0, "nothing before the SPARC code record (8051 boot/runtime/updater) may change"
        for site, entry in ((GET_CS, "GET"), (SET_CS, "SET")):
            word = struct.unpack(">I", b.image[site + ph.CODE_SHIFT : site + ph.CODE_SHIFT + 4])[0]
            assert word >> 30 == 1 and site + 4 * (word & 0x3FFFFFFF) == b.labels[entry]
        seen.add(b.name.filename)
    assert len(seen) == 3


def test_encoder_matches_capstone():
    cs = pytest.importorskip("capstone")
    md = cs.Cs(cs.CS_ARCH_SPARC, cs.CS_MODE_BIG_ENDIAN)
    asm, code = ph.build_hook("c", VM)
    for name, blob in code.items():
        assert len(list(md.disasm(blob, VM.regions[name][0]))) == len(blob) // 4, f"undecodable word in {name}"


# ---- behaviour (every stage) ----
def test_other_codes_reach_the_stock_handlers_untouched(any_stage: Machine):
    m = any_stage
    for code in (0x10, 0x60, 0xE9, 0xE7, 0xF2, 0xFE, 0x00):
        m.log.clear()
        assert m.get(code) is None and m.log == [("get_vcp", code)]
    ours = {0xD6} | ({0x60, 0xEB} if m.stage == "c" else set())
    for code in sorted({0x10, 0x60, 0xEB, 0xF4, 0xF5, 0x04} - ours):
        m.log.clear()
        m.set(code, 1)
        assert m.log == [("set_vcp", code)]


def test_capability_word_and_power_mode(any_stage: Machine):
    m = any_stage
    mh, ml, ch, cl = m.get(0xE8)
    assert (mh, ml) == (0b11, 0) and (ch << 8 | cl) == ph.CAPS[m.stage]
    assert not (ch << 8 | cl) & ph.CAP_MEMORY
    m.w32(SYM["cable_state"], 1)  # HDMI cable out
    assert m.get(0xE8)[0] == 0b01
    assert m.get(0xD6) == (0x00, 0x05, 0x00, 0x01)


def test_set_d6_5_calls_the_stock_power_off(any_stage: Machine):
    m = any_stage
    assert m.set(0xD6, 5)
    assert ("set_power_state", 1) in m.log and not any(e[0] == "set_vcp" for e in m.log)
    m.log.clear()
    m.set(0xD6, 2)
    assert m.log == [("set_vcp", 0xD6)]


def test_p3a_treats_4_as_power_off_and_ignores_wake():
    m = Machine("a")
    assert m.set(0xD6, 4) and m.log == [("set_power_state", 1)]
    m.log.clear()
    m.set(0xD6, 1)
    assert m.log == [("set_vcp", 0xD6)]
    assert not m.mem.keys() & set(range(0xA803C000, 0xA803D000)), "p3a must not write RAM"


@pytest.mark.parametrize("stage", ["b", "c"])
def test_soft_standby_and_wake(stage: str):
    m = Machine(stage)
    assert m.set(0xD6, 4)
    assert m.log == [("panel_on_off", 0, 1), ("led_power_off",)]
    assert m.get(0xD6) == (0, 5, 0, 4) and m.get(0xE8)[1] == 1
    m.log.clear()
    assert m.set(0xD6, 4) and m.log == []  # already in soft standby
    assert m.set(0xD6, 1)
    assert m.log == [("panel_on_off", 1, 1), ("led_power_on",)]
    assert m.get(0xD6) == (0, 5, 0, 1) and m.get(0xE8)[1] == 0
    m.log.clear()
    assert m.set(0xD6, 1) and m.log == []  # wake while on: nothing to do


@pytest.mark.parametrize("stage", ["b", "c"])
def test_heap_growth_turns_the_hook_into_stock(stage: str):
    m = Machine(stage)
    assert m.get(0xE8) is not None
    m.w32(SYM["heap_break"], VM.ram["ring"])  # heap ends exactly below the block: still ours
    assert m.get(0xE8) is not None
    m.w32(SYM["heap_break"], VM.ram["ring"] + 4)
    before = dict(m.mem)
    m.log.clear()
    assert m.get(0xE8) is None and m.get(0xD6) is None and m.get(0xEA) is None
    m.set(0xD6, 4)
    assert m.log == [("get_vcp", 0xE8), ("get_vcp", 0xD6), ("get_vcp", 0xEA), ("set_vcp", 0xD6)]
    assert {k: v for k, v in m.mem.items() if 0xA803C400 <= k < 0xA803D000} == {
        k: v for k, v in before.items() if 0xA803C400 <= k < 0xA803D000
    }


# ---- behaviour (p3c: ring) ----
def test_boot_then_initial_state_then_quiet():
    m = Machine("c")
    assert m.events() == [(0x00, 0, 0), (0x01, 0xEE, 0), (0x06, 0xEE, 1), (0x15, 0xEE, 3)]
    assert m.events() == []
    assert m.get(0xEE) == (0, 0, 1, 1)  # port DP, power on, picture locked
    assert m.get(0xEB) == (0, 0, 0, 4)


def test_record_time_and_clock_use_10ms_units():
    m = Machine("c")
    m.w32(SYM["tick_seconds"], 0x123)
    m.events()
    assert m.get(0xEF) == tuple((0x123 * 100).to_bytes(4, "big"))
    m.set(0xEB, 1)
    assert m.get(0xED) == (1, *(0x123 * 100).to_bytes(3, "big"))


def test_switch_done_after_the_picture_locks():
    m = Machine("c")
    m.events()
    m.log.clear()
    assert not m.set(0x60, 0x11)  # the stock handler performs the switch (the stub answers 0)
    assert m.log == [("set_vcp", 0x60)]
    assert m.events() == [(0x10, 0, 0x11)]
    m.source = 0x00  # on HDMI, mode search
    m.w32(SYM["sync_state"], 2)
    assert m.events() == [(0x01, 0, 1), (0x06, 1, 0)]
    m.w32(SYM["sync_state"], SYM["sync_locked"])
    assert m.events() == [(0x06, 0, 1), (0x11, 1, 1)]
    assert m.get(0xEE) == (1, 0, 1, 1)
    assert m.events() == []


def test_switch_failed_after_the_deadline():
    m = Machine("c")
    m.events()
    m.set(0x60, 0x11)
    m.source = 0x00
    m.w32(SYM["sync_state"], 1)
    assert m.events() == [(0x10, 0, 0x11), (0x01, 0, 1), (0x06, 1, 0)]
    m.w32(SYM["tick_seconds"], 100 + ph.VERDICT_SECONDS)
    assert m.events() == []
    m.w32(SYM["tick_seconds"], 100 + ph.VERDICT_SECONDS + 1)
    assert m.events() == [(0x12, 1, 1)]
    assert m.events() == []


def test_switch_guard_refuses_an_input_without_cable():
    m = Machine("c")
    m.events()
    m.w32(SYM["cable_state"], 1)  # HDMI unplugged
    m.log.clear()
    assert m.set(0x60, 0x11)
    assert m.log == [], "the stock handler must not see a guarded switch"
    assert m.events() == [(0x15, 3, 1), (0x10, 0, 0x11), (0x12, 1, 0)]
    m.log.clear()
    m.set(0x60, 0x0F)  # DP has a cable: goes through
    assert m.log == [("set_vcp", 0x60)]


def test_osd_input_change_has_no_request_event():
    m = Machine("c")
    m.events()
    m.source = 0x00
    assert m.events() == [(0x01, 0, 1)]


def test_power_state_events():
    m = Machine("c")
    m.events()
    m.set(0xD6, 4)
    m.set(0xD6, 1)
    assert m.events() == [(0x14, 1, 4), (0x14, 1, 1)]
    m.set(0xD6, 5)
    assert m.events() == [(0x14, 1, 5)]


def test_ring_wraps_and_keeps_the_newest_records():
    m = Machine("c")
    m.events()
    for k in range(100):
        m.source = 0x00 if k % 2 == 0 else 0x10
        m.get(0xEA)
    head = m.get(0xEA)
    newest = head[2] << 8 | head[3]
    assert newest == 4 + 100
    m.set(0xEB, newest)
    assert m.get(0xEC) == (0x01, 1, 0, newest & 0xFF)  # the last change went back to DP
    m.set(0xEB, newest - 0x40)  # overwritten: the stored sequence byte no longer matches the cursor
    assert m.get(0xEC)[3] == newest & 0xFF != (newest - 0x40) & 0xFF
