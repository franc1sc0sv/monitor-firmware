#!/usr/bin/env python3
"""G5 1021.0: the last USB image. Generic SPARC hook + 8051 POKE/PEEK, so everything else is uploaded over DDC.

SPARC hook (dead region 0x1E14EC, slots at BSS 0xA803CFC0, upload window [0xA803C400, slots end)):
  Set F0/F1  ADDR hi/lo                     Get F3  32-bit word at ADDR (any address)
  Set F4     write value16 (2 bytes, big-endian) at ADDR, ADDR += 2; only inside the upload window/slots
  Set F5     flush; call absolute [TARG] with ARG0..ARG4 in %o0..%o4; RESULT = %o0 (ARG4 shares RESULT's slot)
  Set F6     32-bit store of VALW to [ADDR], only in the DRAM port 0xCF011F80..BF or the 8051 page 0xCF03C000..CFFF

8051 runtime (segment A, record @0x8040): mailbox cmd 0x21 (was DP HDCP key write, a factory command) now POKEs
XDATA[b1:b2] = b3; mailbox cmd 0x03 (was a no-op ack) PEEKs XDATA[b1:b2] into a4b0 and copies a4b0..a4b3 to
mailbox +0xB4 the way cmd 0x14 replies (0xEC10). See docs/targets/g5-falcon/firmware-re.md (FINAL-USB-FLASH PLAN).

    uv run --with keystone-engine --with capstone python firmware/targets/g5-falcon/patches/final_hook.py \
        data/vendor/g5/stock-1008.3/extracted/"M-C5500GGZA-1008.3[C145].img"
"""
from __future__ import annotations
import pathlib, struct, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import devtools_hook as dh  # noqa: E402  (Asm, call-site constants, assembler helpers)
from devtools_hook import Asm, md, f, _call, _hi  # noqa: E402
nv = dh.nv

VERSION = "1021.1"
LIST = 0xA803C600                                  # F8 call list (BSS, 24-byte entries)
SLOTS = dh.SLOTS                                   # 0xA803CFC0 (hardware-proven in 1020.1..1020.3)
ADDR, TARG, RESULT, SAVED, VALW = SLOTS, SLOTS + 4, SLOTS + 0x18, SLOTS + 0x1C, SLOTS + 0x24
UP_LO, UP_HI = 0xA803C400, SLOTS + 0x28            # F4 window: upload area + slots
assert SLOTS == 0xA803CFC0

# ---- 8051 segment A patch (code address -> file offset 0x8060 + addr) ----
SEGA_HDR, SEGA_DATA = 0x8040, 0x8060
POKE_AT, PEEK_AT, SLOT03 = 0xEAAB, 0xEABB, 0x27B6 + 3 * (0x03 - 1)
POKE = bytes.fromhex("90A4AA E0 FE A3 E0 FF A3 E0 8E83 8F82 F0 22".replace(" ", ""))
PEEK = bytes.fromhex(("90A4AA E0 FE A3 E0 FF 8E83 8F82 E0 90A4B0 F0"
                      " 7B01 7AA4 79B0 90A4BC 7401 F0 7FB4 12C336 022BBC").replace(" ", ""))
STOCK_EAAB = bytes.fromhex("90d5e0e0ff7422f0e490d5e1f090d5e2f090bff3f0fdfc74002df582743e3cf583e090d5e3f00dbd00010c")
assert len(POKE) == 16 and len(PEEK) == 37 and PEEK_AT + len(PEEK) <= 0xEAE2


def build_sparc() -> tuple[int, bytes, int]:
    a = Asm(dh.REGION)
    a.label("GET")
    a.ins("cmp %o0, 0xF3"); a.br("be", "GW"); a.ins("nop")
    a.br("ba", dh.GETVCP); a.ins("nop")
    a.label("GW")
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g3"); a.ins("ld [%g3], %g3")
    a.ins("srl %g3, 24, %g4"); a.ins("stb %g4, [%o1]")
    a.ins("srl %g3, 16, %g4"); a.ins("stb %g4, [%o1+1]")
    a.ins("srl %g3, 8, %g4"); a.ins("stb %g4, [%o1+2]")
    a.ins("stb %g3, [%o1+3]")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SET")
    a.ins("ldub [%fp-0x2c], %g3"); a.ins("ldub [%fp-0x2b], %g4"); a.ins("sll %g3, 8, %g3"); a.ins("or %g3, %g4, %g3")
    for code, lab in ((0xF0, "SF0"), (0xF1, "SF1"), (0xF4, "SF4"), (0xF5, "SF5"), (0xF6, "SF6"), (0xF8, "SF8")):
        a.ins(f"cmp %o0, {code}"); a.br("be", lab); a.ins("nop")
    a.br("ba", dh.SETVCP); a.ins("nop")
    a.label("SF0")
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g5")
    a.ins("sll %g5, 16, %g5"); a.ins("srl %g5, 16, %g5"); a.ins("sll %g3, 16, %g3"); a.ins("or %g3, %g5, %g3")
    a.ins("st %g3, [%g2]"); a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF1")
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g5")
    a.ins("srl %g5, 16, %g5"); a.ins("sll %g5, 16, %g5"); a.ins("or %g5, %g3, %g3")
    a.ins("st %g3, [%g2]"); a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF4")   # 2 bytes per frame into [UP_LO, UP_HI - 1]
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g5")
    a.addr("%g2", UP_LO); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "SEND"); a.ins("nop")
    a.addr("%g2", UP_HI - 1); a.ins("subcc %g5, %g2, %g0"); a.br("bgeu", "SEND"); a.ins("nop")
    a.ins("srl %g3, 8, %g3"); a.ins("stb %g3, [%g5]"); a.ins("stb %g4, [%g5+1]")
    a.addr("%g2", ADDR); a.ins("add %g5, 2, %g5"); a.ins("st %g5, [%g2]")
    a.label("SEND"); a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF5")   # absolute call with 5 args; flush the I-cache first (uploaded code)
    a.addr("%g2", SAVED); a.ins("st %o7, [%g2]")
    a.addr("%g2", TARG); a.ins("ld [%g2], %g1")
    a.ins("ld [%g2+4], %o0"); a.ins("ld [%g2+8], %o1"); a.ins("ld [%g2+0xC], %o2")
    a.ins("ld [%g2+0x10], %o3"); a.ins("ld [%g2+0x14], %o4")
    a.ins("flush %g1")
    a.ins("jmpl %g1, %o7"); a.ins("nop")
    a.addr("%g2", RESULT); a.ins("st %o0, [%g2]")
    a.addr("%g2", SAVED); a.ins("ld [%g2], %o7")
    a.ins("retl"); a.ins("mov 1, %o0")
    a.label("SF8")   # run the call list at LIST: entries {target, a0..a4}; result overwrites target; stop at target 0
    # (BSS is not executable on this chip, so multi-step sequences run here, in code RAM, calling firmware only)
    a.ins("save %sp, -0x60, %sp")
    a.addr("%l0", LIST)
    a.label("S8L")
    a.ins("ld [%l0], %g1"); a.ins("cmp %g1, 0"); a.br("be", "S8D"); a.ins("nop")
    a.ins("ld [%l0+4], %o0"); a.ins("ld [%l0+8], %o1"); a.ins("ld [%l0+0xC], %o2")
    a.ins("ld [%l0+0x10], %o3"); a.ins("ld [%l0+0x14], %o4")
    a.ins("jmpl %g1, %o7"); a.ins("nop")
    a.ins("st %o0, [%l0]"); a.ins("add %l0, 24, %l0"); a.br("ba", "S8L"); a.ins("nop")
    a.label("S8D")
    a.ins("ret"); a.ins("restore %g0, 1, %o0")
    a.label("SF6")
    a.addr("%g2", ADDR); a.ins("ld [%g2], %g5")
    a.addr("%g2", dh.DRAM_LO); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "W6SPI"); a.ins("nop")
    a.addr("%g2", dh.DRAM_HI); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "W6GO"); a.ins("nop")
    a.label("W6SPI")
    a.ins(f"sethi {_hi(dh.SPI_LO)}, %g2"); a.ins("subcc %g5, %g2, %g0"); a.br("blu", "SEND6"); a.ins("nop")
    a.ins(f"sethi {_hi(dh.SPI_HI)}, %g2"); a.ins("subcc %g5, %g2, %g0"); a.br("bgeu", "SEND6"); a.ins("nop")
    a.label("W6GO")
    a.addr("%g2", VALW); a.ins("ld [%g2], %g4"); a.ins("st %g4, [%g5]")
    a.label("SEND6"); a.ins("retl"); a.ins("mov 1, %o0")
    code = a.assemble()
    assert len(code) <= dh.CODE_MAX, f"hook {len(code)}B > {dh.CODE_MAX}"
    return a.labels["SET"], code, a.labels["GET"]


def patch_8051(d: bytearray) -> None:
    def at(addr: int) -> int: return SEGA_DATA + addr
    assert bytes(d[at(POKE_AT):at(POKE_AT) + len(STOCK_EAAB)]) == STOCK_EAAB, "unexpected bytes at 0xEAAB"
    assert bytes(d[at(SLOT03):at(SLOT03) + 3]) == bytes.fromhex("022BBC"), "cmd 0x03 slot is not the stock ack"
    assert bytes(d[at(0x29AF):at(0x29AF) + 3]) == bytes.fromhex("12EAAB"), "cmd 0x21 handler does not call 0xEAAB"
    d[at(POKE_AT):at(POKE_AT) + 16] = POKE
    d[at(PEEK_AT):at(PEEK_AT) + 37] = PEEK
    d[at(SLOT03):at(SLOT03) + 3] = bytes([0x02, PEEK_AT >> 8, PEEK_AT & 0xFF])
    f0, f1, size, _ = struct.unpack(">HHII", d[SEGA_HDR:SEGA_HDR + 12])
    assert (f0, f1, size) == (1, 0, 0xFAC0)
    d[SEGA_HDR + 8:SEGA_HDR + 12] = struct.pack(">I", sum(d[SEGA_DATA:SEGA_DATA + size]) & 0xFFFF)


def main(stock_path: str, version: str = VERSION) -> None:
    stock = pathlib.Path(stock_path).read_bytes()
    d = bytearray(stock)
    set_entry, code, get_entry = build_sparc()
    d[f(dh.REGION):f(dh.REGION) + len(code)] = code
    d[f(dh.GET_CS):f(dh.GET_CS) + 4] = _call(dh.GET_CS, get_entry)
    d[f(dh.SET_CS):f(dh.SET_CS) + 4] = _call(dh.SET_CS, set_entry)
    for i in md.disasm(bytes(d[f(dh.REGION):f(dh.REGION) + len(code)]), dh.REGION):
        if i.mnemonic in ("ba", "be", "bne", "blu", "bgeu", "call") and i.op_str.startswith("0x"):
            t = int(i.op_str, 16)
            assert t in (dh.GETVCP, dh.SETVCP) or dh.REGION <= t < dh.REGION + len(code), f"bad target @ {hex(i.address)}"
    patch_8051(d)
    out, name = nv.restamp(bytes(d), version, family=b"M-C5500GGZA")
    nv.verify_stock(out, name.filename, family=b"M-C5500GGZA")
    dst = pathlib.Path(stock_path).parent.parent.parent / "builds" / name.filename
    dst.write_bytes(out)
    diff = [i for i in range(len(stock)) if stock[i] != out[i]]
    in8051 = [i for i in diff if SEGA_HDR <= i < SEGA_DATA + 0xFAC0]
    print(f"built {dst}  hook {len(code)}B, {len(diff)} bytes changed ({len(in8051)} in the 8051 record), sum16 {name.tag}")
    print(f"  8051 changed offsets: {hex(min(in8051))}..{hex(max(in8051))}  GET={hex(get_entry)} SET={hex(set_entry)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
