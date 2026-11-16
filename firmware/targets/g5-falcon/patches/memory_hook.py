#!/usr/bin/env python3
"""G5 memory read/write over DDC: VCP F0/F1 (address hi/lo), F2 (read 4), F4 (write 1).

Extends the validated proof hook. Redirects the dispatcher's Get-VCP call (0x103EBC) and Set-VCP call (0x104170)
to routines in reclaimed dead code (0x1E3428, 0x188 bytes, 0 callers), with a 4-byte current-address scratch there.
Addresses are range-guarded to [0x100000, 0x2F8000) (the loaded firmware RAM) so a bad read/write can't touch MMIO.
Builds the patched image with the sum16 recomputed. See docs/targets/g5-falcon/firmware-re.md.

Usage:
    uv run --with keystone-engine --with capstone python firmware/targets/g5-falcon/patches/memory_hook.py \
        data/vendor/g5/stock-1008.3/extracted/"M-C5500GGZA-1008.3[C145].img"
"""
from __future__ import annotations
import struct, sys, pathlib
from keystone import Ks, KS_ARCH_SPARC, KS_MODE_BIG_ENDIAN, KS_MODE_SPARC32
from capstone import Cs, CS_ARCH_SPARC, CS_MODE_BIG_ENDIAN
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "tools/mfw/src"))
from mfw import novatek as nv  # noqa: E402

CODE_SHIFT = 0x2E000
f = lambda va: va + CODE_SHIFT
GETVCP, SETVCP = 0x1882AC, 0x1869BC
GET_CALLSITE, SET_CALLSITE = 0x103EBC, 0x104170
REGION = 0x1E3428                     # dead func, 0x188 bytes, 0 callers
VAR = REGION + 0x180                  # 4-byte current-address scratch at the tail
LO, HI = 0x100000, 0x2F8000           # safe RAM read/write window
NEW_VERSION = "1011.0"                # must be higher than the version already on the unit (updater rejects <=)

ks = Ks(KS_ARCH_SPARC, KS_MODE_SPARC32 | KS_MODE_BIG_ENDIAN)
md = Cs(CS_ARCH_SPARC, CS_MODE_BIG_ENDIAN)

# keystone mis-encodes SPARC call/Bicc displacements, so hand-encode all control flow.
COND = {"ba": 8, "be": 1, "bne": 9, "blu": 5, "bgeu": 0xD}
def _i(line, addr):   # one non-branch instruction via keystone
    enc, _ = ks.asm(line, addr); return bytes(enc)
def _call(pc, tgt): return struct.pack(">I", 0x40000000 | (((tgt - pc) >> 2) & 0x3FFFFFFF))
def _b(cond, pc, tgt): return struct.pack(">I", (COND[cond] << 25) | (0b010 << 22) | (((tgt - pc) >> 2) & 0x3FFFFF))

# &VAR built with sethi/or (VAR = (hi<<10)|lo)
VHI, VLO = (VAR >> 10) & 0x3FFFFF, VAR & 0x3FF
assert (VHI << 10 | VLO) == VAR


class Asm:
    """Two-pass assembler over a tiny label set so branch targets resolve."""
    def __init__(self, base): self.base = base; self.items = []; self.labels = {}
    def label(self, name): self.labels[name] = None; self.items.append(("label", name))
    def ins(self, line): self.items.append(("ins", line))
    def call(self, tgt): self.items.append(("call", tgt))
    def br(self, cond, tgt): self.items.append(("br", cond, tgt))  # tgt: int or label name
    def _resolve(self):
        pc = self.base
        for it in self.items:
            if it[0] == "label": self.labels[it[1]] = pc
            else: pc += 4
    def assemble(self):
        self._resolve(); pc = self.base; out = b""
        for it in self.items:
            if it[0] == "label": continue
            if it[0] == "ins": out += _i(it[1], pc)
            elif it[0] == "call": out += _call(pc, it[1])
            elif it[0] == "br":
                tgt = self.labels[it[2]] if isinstance(it[2], str) else it[2]
                out += _b(it[1], pc, tgt)
            pc += 4
        return out


def build_region() -> tuple[int, bytes, int]:
    a = Asm(REGION)
    # ---- GET entry (F2 read) : %o0=code, %o1=reply buf ----
    a.label("GET")
    a.ins("cmp %o0, 0xF2"); a.br("bne", GETVCP); a.ins("nop")
    a.ins(f"sethi {VHI}, %g2"); a.ins(f"or %g2, {VLO}, %g2")   # g2 = &VAR
    a.ins("ld [%g2], %g3")                                      # g3 = addr
    a.ins(f"sethi {(LO >> 10) & 0x3FFFFF}, %g5"); a.ins("subcc %g3, %g5, %g0"); a.br("blu", "GBAD")
    a.ins("nop")
    a.ins(f"sethi {(HI >> 10) & 0x3FFFFF}, %g5"); a.ins("subcc %g3, %g5, %g0"); a.br("bgeu", "GBAD")
    a.ins("nop")
    a.ins("ldub [%g3], %g4"); a.ins("stb %g4, [%o1]")
    a.ins("ldub [%g3+1], %g4"); a.ins("stb %g4, [%o1+1]")
    a.ins("ldub [%g3+2], %g4"); a.ins("stb %g4, [%o1+2]")
    a.ins("ldub [%g3+3], %g4"); a.ins("stb %g4, [%o1+3]")
    a.ins("add %g3, 4, %g3"); a.ins("st %g3, [%g2]")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("GBAD")
    a.ins("mov 0xFF, %g4")
    a.ins("stb %g4, [%o1]"); a.ins("stb %g4, [%o1+1]"); a.ins("stb %g4, [%o1+2]"); a.ins("stb %g4, [%o1+3]")
    a.ins("retl"); a.ins("mov 1, %o0")
    # ---- SET entry (F0/F1/F4) : %o0=code, value at [%fp-0x2c]=hi,[%fp-0x2b]=lo ----
    a.label("SET")
    a.ins(f"sethi {VHI}, %g2"); a.ins(f"or %g2, {VLO}, %g2")   # g2 = &VAR
    a.ins("ldub [%fp-0x2c], %g3"); a.ins("ldub [%fp-0x2b], %g4")
    a.ins("sll %g3, 8, %g3"); a.ins("or %g3, %g4, %g3")        # g3 = value16
    a.ins("ld [%g2], %g5")                                      # g5 = old addr
    a.ins("cmp %o0, 0xF0"); a.br("be", "SF0"); a.ins("nop")
    a.ins("cmp %o0, 0xF1"); a.br("be", "SF1"); a.ins("nop")
    a.ins("cmp %o0, 0xF4"); a.br("be", "SF4"); a.ins("nop")
    a.br("ba", SETVCP); a.ins("nop")                           # not ours -> real SetVcp
    a.label("SF0")   # addr = (value16<<16) | (addr & 0xFFFF)
    a.ins("sll %g5, 16, %g5"); a.ins("srl %g5, 16, %g5")       # g5 = addr low16
    a.ins("sll %g3, 16, %g3"); a.ins("or %g3, %g5, %g3"); a.ins("st %g3, [%g2]")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF1")   # addr = (addr & 0xFFFF0000) | value16
    a.ins("srl %g5, 16, %g5"); a.ins("sll %g5, 16, %g5")       # g5 = addr high16
    a.ins("or %g5, %g3, %g3"); a.ins("st %g3, [%g2]")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF4")   # write value_low byte at addr (guarded), addr += 1
    a.ins(f"sethi {(LO >> 10) & 0x3FFFFF}, %g2"); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "SEND")
    a.ins("nop")
    a.ins(f"sethi {(HI >> 10) & 0x3FFFFF}, %g2"); a.ins("subcc %g5, %g2, %g0"); a.br("bgeu", "SEND")
    a.ins("nop")
    a.ins("stb %g4, [%g5]")                                     # write value_low
    a.ins(f"sethi {VHI}, %g2"); a.ins(f"or %g2, {VLO}, %g2"); a.ins("add %g5, 1, %g5"); a.ins("st %g5, [%g2]")
    a.label("SEND")
    a.ins("retl"); a.ins("mov 1, %o0")
    code = a.assemble()
    assert len(code) <= (VAR - REGION), f"hook ({len(code)}B) overruns the scratch var"
    return a.labels["SET"], code, a.labels["GET"]


def main(stock_path: str) -> None:
    stock = pathlib.Path(stock_path).read_bytes()
    d = bytearray(stock)
    set_entry, code, get_entry = build_region()
    d[f(REGION):f(REGION) + len(code)] = code
    d[f(VAR):f(VAR) + 4] = struct.pack(">I", LO)       # init current address to the start of the safe window
    d[f(GET_CALLSITE):f(GET_CALLSITE) + 4] = _call(GET_CALLSITE, get_entry)
    d[f(SET_CALLSITE):f(SET_CALLSITE) + 4] = _call(SET_CALLSITE, set_entry)

    # verify the two redirects and that every branch/call in the region resolves to a sane target
    gi = next(md.disasm(bytes(d[f(GET_CALLSITE):f(GET_CALLSITE) + 4]), GET_CALLSITE))
    si = next(md.disasm(bytes(d[f(SET_CALLSITE):f(SET_CALLSITE) + 4]), SET_CALLSITE))
    assert gi.mnemonic == "call" and int(gi.op_str, 16) == get_entry
    assert si.mnemonic == "call" and int(si.op_str, 16) == set_entry
    for i in md.disasm(bytes(d[f(REGION):f(REGION) + len(code)]), REGION):
        if i.mnemonic in ("ba", "be", "bne", "blu", "bgeu", "call"):
            t = int(i.op_str, 16)
            assert t == GETVCP or t == SETVCP or REGION <= t < REGION + len(code), f"bad target {i.op_str} @ {hex(i.address)}"

    out, name = nv.restamp(bytes(d), NEW_VERSION, family=b"M-C5500GGZA")
    nv.verify_stock(out, name.filename, family=b"M-C5500GGZA")
    dst = pathlib.Path(stock_path).parent.parent.parent / "builds" / name.filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    changed = sum(1 for i in range(len(stock)) if stock[i] != out[i])
    print(f"built {dst}  ({len(code)}B hook, {changed} bytes changed, sum16 {name.tag})")
    print(f"  GET={hex(get_entry)} SET={hex(set_entry)} VAR={hex(VAR)}")


if __name__ == "__main__":
    main(sys.argv[1])
