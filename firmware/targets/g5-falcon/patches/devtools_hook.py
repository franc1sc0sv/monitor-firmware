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
RELOC = 0x320                          # code runs at file VA + 0x320 (hardware-confirmed delta)
CODE_MAX = 0x280                       # whole verified-dead region
# Slots history: 1019.x used 0xA8039A00, inside a live settings table (hardware-confirmed 2026-11-16). 1020.0 put them
# in the dead code region, but code RAM ignores stores (hardware-confirmed: F0/F1 had no effect, F3 then trapped on
# the stale unaligned ADDR). 1020.1: the top 0x40 bytes of the largest unreferenced BSS gap (0xA803C3E8..0xA803D000;
# arrays grow up from their base, so the end just below the next referenced symbol is the least exposed spot).
SLOTS = 0xA803CFC0
ADDR, TARG, ARG0, RESULT, SAVED, DELTA = SLOTS, SLOTS + 4, SLOTS + 8, SLOTS + 0x18, SLOTS + 0x1C, SLOTS + 0x20
VALW = SLOTS + 0x24                    # 32-bit value staged for the F6 word-write
SPI_LO, SPI_HI = 0xCF03C000, 0xCF03D000
assert SPI_LO % 0x400 == 0 and SPI_HI % 0x400 == 0, "SPI bounds are compared with sethi only"  # SPI controller MMIO window (F6 word-write guard)
RLO, RHI = 0x100000, 0x2F8000          # read window (code/data image)
WLO, WHI = SLOTS, SLOTS + 0x28         # F4 byte-write window: the slots only
DRAM_LO, DRAM_HI = 0xCF011F80, 0xCF011FC0  # DRAM access port (second F6 window; see firmware-re.md)
NEW_VERSION = "1020.2"           # slots out of settings RAM; F6 also reaches the DRAM access port
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
    def pccall(self): self.items.append(("pccall",))                   # call .+8 (%o7 = runtime PC of this instr)
    def loadva(self, reg, lab):                                        # reg = the *file* VA of a label (sethi/or)
        self.items.append(("lvh", reg, lab)); self.items.append(("lvl", reg, lab))
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
            elif it[0] == "pccall": out += _call(pc, pc + 8)
            elif it[0] == "lvh": out += _i(f"sethi {_hi(self.labels[it[2]])}, {it[1]}", pc)
            elif it[0] == "lvl": out += _i(f"or {it[1]}, {_lo(self.labels[it[2]])}, {it[1]}", pc)
            pc += 4
        return out


def build() -> tuple[int, bytes, int]:
    a = Asm(REGION)
    # ---- GET (F2): read 4 bytes at ADDR, in [RLO,RHI) or [WLO,WHI) ----
    a.label("GET")   # F2 = 4 byte-reads at ADDR ; F3 = one 32-bit word read at ADDR (for MMIO). Read any address.
    a.ins("cmp %o0, 0xF2"); a.br("be", "GB4"); a.ins("nop")
    a.ins("cmp %o0, 0xF3"); a.br("be", "GW"); a.ins("nop")
    a.br("ba", GETVCP); a.ins("nop")
    a.label("GB4")
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g3")
    for k in range(4): a.ins(f"ldub [%g3+{k}], %g4" if k else "ldub [%g3], %g4"); a.ins(f"stb %g4, [%o1+{k}]" if k else "stb %g4, [%o1]")
    a.addr("%g2", ADDR); a.ins("add %g3, 4, %g3"); a.ins("st %g3, [%g2]")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("GW")   # 32-bit word load (MMIO needs word access); returns the word big-endian in the 4 reply bytes
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g3"); a.ins("ld [%g3], %g3")   # g3 = word at [ADDR]
    a.ins("srl %g3, 24, %g4"); a.ins("stb %g4, [%o1]")
    a.ins("srl %g3, 16, %g4"); a.ins("stb %g4, [%o1+1]")
    a.ins("srl %g3, 8, %g4"); a.ins("stb %g4, [%o1+2]")
    a.ins("stb %g3, [%o1+3]")
    a.ins("retl"); a.ins("mov 1, %o0")
    # ---- SET (F0/F1/F4/F5) ----
    a.label("SET")
    a.ins("ldub [%fp-0x2c], %g3"); a.ins("ldub [%fp-0x2b], %g4"); a.ins("sll %g3, 8, %g3"); a.ins("or %g3, %g4, %g3")  # value16 -> g3 (g4=low)
    a.ins("cmp %o0, 0xF0"); a.br("be", "SF0"); a.ins("nop")
    a.ins("cmp %o0, 0xF1"); a.br("be", "SF1"); a.ins("nop")
    a.ins("cmp %o0, 0xF4"); a.br("be", "SF4"); a.ins("nop")
    a.ins("cmp %o0, 0xF5"); a.br("be", "SF5"); a.ins("nop")
    a.ins("cmp %o0, 0xF6"); a.br("be", "SF6"); a.ins("nop")
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
    # full 32-bit bounds (sethi alone drops the low 10 bits: 1020.1 bug, the slot window collapsed to empty)
    a.addr("%g2", WLO); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "SEND"); a.ins("nop")
    a.addr("%g2", WHI); a.ins("subcc %g5, %g2, %g0"); a.br("bgeu", "SEND"); a.ins("nop")
    a.ins("stb %g4, [%g5]"); a.addr("%g2", ADDR); a.ins("add %g5, 1, %g5"); a.ins("st %g5, [%g2]")
    a.label("SEND"); a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF5")   # call TARG(arg0..arg3) with the code relocated at runtime; RESULT = return value
    a.addr("%g2", SAVED); a.ins("st %o7, [%g2]")           # save hook return (pccall below clobbers %o7)
    a.label("PCM"); a.pccall(); a.ins("nop")               # %o7 = runtime addr of PCM
    a.loadva("%g1", "PCM"); a.ins("sub %o7, %g1, %g4")     # %g4 = delta = runtime(PCM) - file VA(PCM)
    a.addr("%g2", TARG); a.ins("ld [%g2], %g1"); a.ins("add %g1, %g4, %g1")   # target_runtime = file VA + delta
    a.ins("ld [%g2+4], %o0"); a.ins("ld [%g2+8], %o1"); a.ins("ld [%g2+0xC], %o2"); a.ins("ld [%g2+0x10], %o3")
    a.ins("jmpl %g1, %o7"); a.ins("nop")                   # call target
    a.addr("%g2", RESULT); a.ins("st %o0, [%g2]")          # store return value
    a.addr("%g2", SAVED); a.ins("ld [%g2], %o7")           # restore hook return
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF6")   # write 32-bit VALW to [ADDR], only if ADDR is in the SPI controller MMIO window
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g5")            # g5 = target MMIO addr
    a.addr("%g2", DRAM_LO); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "W6SPI"); a.ins("nop")
    a.addr("%g2", DRAM_HI); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "W6GO"); a.ins("nop")
    a.label("W6SPI")
    a.ins(f"sethi {_hi(SPI_LO)}, %g2"); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "SEND6"); a.ins("nop")
    a.ins(f"sethi {_hi(SPI_HI)}, %g2"); a.ins("subcc %g5, %g2, %g0"); a.br("bgeu", "SEND6"); a.ins("nop")
    a.label("W6GO")
    a.addr("%g2", VALW); a.ins("ld [%g2], %g4"); a.ins("st %g4, [%g5]")   # *ADDR = VALW (32-bit)
    a.label("SEND6"); a.ins("retl"); a.ins("mov 1, %o0")
    code = a.assemble()
    assert len(code) <= CODE_MAX, f"hook ({len(code)}B) overruns its budget (slots follow at {hex(SLOTS)})"
    return a.labels["SET"], code, a.labels["GET"]


def main(stock_path: str, version: str = NEW_VERSION) -> None:
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
    out, name = nv.restamp(bytes(d), version, family=b"M-C5500GGZA")
    nv.verify_stock(out, name.filename, family=b"M-C5500GGZA")
    dst = pathlib.Path(stock_path).parent.parent.parent / "builds" / name.filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    changed = sum(1 for i in range(len(stock)) if stock[i] != out[i])
    print(f"built {dst}  ({len(code)}B hook, {changed} bytes changed, sum16 {name.tag})")
    print(f"  GET={hex(get_entry)} SET={hex(set_entry)} SLOTS={hex(SLOTS)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])  # optional 2nd arg: version string (same code, new version so the updater accepts it)
