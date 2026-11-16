#!/usr/bin/env python3
"""G5 all-in-one dev hook over DDC: memory read/write + a call-any-firmware-function primitive.

One image, flashed once by USB, then everything is driven over HDMI/DDC (fast, no more USB swaps):
  Set F0/F1  set the 32-bit ADDR (hi/lo)
  Get F2     read 4 bytes at ADDR, ADDR += 4           (reads code image or BSS)
  Set F4     write value_low byte at ADDR, ADDR += 1   (writable BSS only)
  Set F5     call SLOTS.target(arg0..arg3); return value stored at RESULT  <-- read it back with F2

The call primitive lets us invoke the firmware's own flash/erase/checksum routines (and SPARC<->8051 paths) live over
DDC, so the flasher is developed and debugged without reflashing. Data/debug slots live in writable BSS and are read
back with F2. See docs/targets/g5-falcon/firmware-re.md.

Slots (writable BSS, contiguous):
  ADDR +0x00  memory pointer         ARG2 +0x10
  TARG +0x04  call target address    ARG3 +0x14
  ARG0 +0x08                         RESULT +0x18  (return value of the last call)
  ARG1 +0x0C                         SAVED  +0x1C  (hook's own return addr, across the inner call)

Hook code goes in the verified-dead function at 0x1E14EC (0x280 bytes, 0 callers, no pointers into it).

Usage:
    uv run --with keystone-engine --with capstone python firmware/targets/g5-falcon/patches/devtools_hook.py \
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
GET_CS, SET_CS = 0x103EBC, 0x104170
REGION = 0x1E14EC                      # verified-dead, 0x280 bytes
SLOTS = 0xA8039A00                     # writable BSS
ADDR, TARG, ARG0, RESULT, SAVED = SLOTS, SLOTS + 4, SLOTS + 8, SLOTS + 0x18, SLOTS + 0x1C
RLO, RHI = 0x100000, 0x2F8000          # read window (code/data image)
WLO, WHI = 0xA8034000, 0xA803C400      # read+write window (BSS)
NEW_VERSION = "1016.0"
_hi = lambda a: (a >> 10) & 0x3FFFFF
_lo = lambda a: a & 0x3FF

ks = Ks(KS_ARCH_SPARC, KS_MODE_SPARC32 | KS_MODE_BIG_ENDIAN)
md = Cs(CS_ARCH_SPARC, CS_MODE_BIG_ENDIAN)
COND = {"ba": 8, "be": 1, "bne": 9, "blu": 5, "bgeu": 0xD}
def _i(line, addr): e, _ = ks.asm(line, addr); return bytes(e)
def _call(pc, tgt): return struct.pack(">I", 0x40000000 | (((tgt - pc) >> 2) & 0x3FFFFFFF))
def _b(cond, pc, tgt): return struct.pack(">I", (COND[cond] << 25) | (0b010 << 22) | (((tgt - pc) >> 2) & 0x3FFFFF))


class Asm:
    def __init__(self, base): self.base = base; self.items = []; self.labels = {}
    def label(self, n): self.items.append(("L", n))
    def ins(self, s): self.items.append(("i", s))
    def addr(self, reg, a):                       # reg = absolute address a (sethi/or)
        self.ins(f"sethi {_hi(a)}, {reg}"); self.ins(f"or {reg}, {_lo(a)}, {reg}")
    def br(self, c, t): self.items.append(("b", c, t))
    def assemble(self):
        pc = self.base
        for it in self.items:
            if it[0] == "L": self.labels[it[1]] = pc
            else: pc += 4
        pc = self.base; out = b""
        for it in self.items:
            if it[0] == "L": continue
            if it[0] == "i": out += _i(it[1], pc)
            elif it[0] == "b": out += _b(it[1], pc, self.labels[it[2]] if isinstance(it[2], str) else it[2])
            pc += 4
        return out


def build() -> tuple[int, bytes, int]:
    a = Asm(REGION)
    # ---- GET (F2): read 4 bytes at ADDR, in [RLO,RHI) or [WLO,WHI) ----
    a.label("GET")
    a.ins("cmp %o0, 0xF2"); a.br("bne", GETVCP); a.ins("nop")
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g3")
    a.ins(f"sethi {_hi(RLO)}, %g5"); a.ins("subcc %g3, %g5, %g0"); a.br("blu", "GT2"); a.ins("nop")
    a.ins(f"sethi {_hi(RHI)}, %g5"); a.ins("subcc %g3, %g5, %g0"); a.br("blu", "GOK"); a.ins("nop")
    a.label("GT2")
    a.ins(f"sethi {_hi(WLO)}, %g5"); a.ins("subcc %g3, %g5, %g0"); a.br("blu", "GBAD"); a.ins("nop")
    a.ins(f"sethi {_hi(WHI)}, %g5"); a.ins("subcc %g3, %g5, %g0"); a.br("bgeu", "GBAD"); a.ins("nop")
    a.label("GOK")
    for k in range(4): a.ins(f"ldub [%g3+{k}], %g4" if k else "ldub [%g3], %g4"); a.ins(f"stb %g4, [%o1+{k}]" if k else "stb %g4, [%o1]")
    a.addr("%g2", ADDR); a.ins("add %g3, 4, %g3"); a.ins("st %g3, [%g2]")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("GBAD")
    a.ins("mov 0xFF, %g4")
    for k in range(4): a.ins(f"stb %g4, [%o1+{k}]" if k else "stb %g4, [%o1]")
    a.ins("retl"); a.ins("mov 1, %o0")
    # ---- SET (F0/F1/F4/F5) ----
    a.label("SET")
    a.ins("ldub [%fp-0x2c], %g3"); a.ins("ldub [%fp-0x2b], %g4"); a.ins("sll %g3, 8, %g3"); a.ins("or %g3, %g4, %g3")  # value16 -> g3 (g4=low)
    a.ins("cmp %o0, 0xF0"); a.br("be", "SF0"); a.ins("nop")
    a.ins("cmp %o0, 0xF1"); a.br("be", "SF1"); a.ins("nop")
    a.ins("cmp %o0, 0xF4"); a.br("be", "SF4"); a.ins("nop")
    a.ins("cmp %o0, 0xF5"); a.br("be", "SF5"); a.ins("nop")
    a.br("ba", SETVCP); a.ins("nop")
    a.label("SF0")   # ADDR = (value16<<16) | (ADDR & 0xFFFF)
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g5")
    a.ins("sll %g5, 16, %g5"); a.ins("srl %g5, 16, %g5"); a.ins("sll %g3, 16, %g3"); a.ins("or %g3, %g5, %g3"); a.ins("st %g3, [%g2]")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF1")   # ADDR = (ADDR & 0xFFFF0000) | value16
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g5")
    a.ins("srl %g5, 16, %g5"); a.ins("sll %g5, 16, %g5"); a.ins("or %g5, %g3, %g3"); a.ins("st %g3, [%g2]")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF4")   # write value_low (g4) at ADDR if in [WLO,WHI), ADDR += 1
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g5")
    a.ins(f"sethi {_hi(WLO)}, %g2"); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "SEND"); a.ins("nop")
    a.ins(f"sethi {_hi(WHI)}, %g2"); a.ins("subcc %g5, %g2, %g0"); a.br("bgeu", "SEND"); a.ins("nop")
    a.ins("stb %g4, [%g5]"); a.addr("%g2", ADDR); a.ins("add %g5, 1, %g5"); a.ins("st %g5, [%g2]")
    a.label("SEND"); a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF5")   # call TARG(arg0..arg3); RESULT = return value
    a.addr("%g2", SAVED); a.ins("st %o7, [%g2]")           # preserve hook return across the inner call
    a.addr("%g2", TARG)
    a.ins("ld [%g2], %g1")                                  # target
    a.ins("ld [%g2+4], %o0"); a.ins("ld [%g2+8], %o1"); a.ins("ld [%g2+0xC], %o2"); a.ins("ld [%g2+0x10], %o3")
    a.ins("jmpl %g1, %o7"); a.ins("nop")                    # call target
    a.addr("%g2", RESULT); a.ins("st %o0, [%g2]")           # store return value
    a.addr("%g2", SAVED); a.ins("ld [%g2], %o7")            # restore hook return
    a.ins("retl"); a.ins("mov 1, %o0")
    code = a.assemble()
    assert len(code) <= 0x280, f"hook ({len(code)}B) overruns the dead region"
    return a.labels["SET"], code, a.labels["GET"]


def main(stock_path: str) -> None:
    stock = pathlib.Path(stock_path).read_bytes()
    d = bytearray(stock)
    set_entry, code, get_entry = build()
    d[f(REGION):f(REGION) + len(code)] = code
    d[f(GET_CS):f(GET_CS) + 4] = _call(GET_CS, get_entry)
    d[f(SET_CS):f(SET_CS) + 4] = _call(SET_CS, set_entry)
    # verify both redirects and every in-region control-flow target
    assert int(next(md.disasm(bytes(d[f(GET_CS):f(GET_CS) + 4]), GET_CS)).op_str, 16) == get_entry
    assert int(next(md.disasm(bytes(d[f(SET_CS):f(SET_CS) + 4]), SET_CS)).op_str, 16) == set_entry
    for i in md.disasm(bytes(d[f(REGION):f(REGION) + len(code)]), REGION):
        if i.mnemonic in ("ba", "be", "bne", "blu", "bgeu", "call") and i.op_str.startswith("0x"):
            t = int(i.op_str, 16)
            assert t in (GETVCP, SETVCP) or REGION <= t < REGION + len(code), f"bad target {i.op_str} @ {hex(i.address)}"
    out, name = nv.restamp(bytes(d), NEW_VERSION, family=b"M-C5500GGZA")
    nv.verify_stock(out, name.filename, family=b"M-C5500GGZA")
    dst = pathlib.Path(stock_path).parent.parent.parent / "builds" / name.filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    changed = sum(1 for i in range(len(stock)) if stock[i] != out[i])
    print(f"built {dst}  ({len(code)}B hook, {changed} bytes changed, sum16 {name.tag})")
    print(f"  GET={hex(get_entry)} SET={hex(set_entry)} SLOTS={hex(SLOTS)}")


if __name__ == "__main__":
    main(sys.argv[1])
