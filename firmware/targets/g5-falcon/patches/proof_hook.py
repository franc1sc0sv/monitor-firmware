#!/usr/bin/env python3
"""Build the G5 proof-of-hook patch: a new Get-VCP code 0xF2 that returns a magic value.

Validates the DDC command-dispatcher hook on hardware before memory addressing is added. Needs the user's own
stock image (not shipped); writes the patched image next to it. See docs/targets/g5-falcon/firmware-re.md.

Usage:
    uv run --with keystone-engine --with capstone python firmware/targets/g5-falcon/patches/proof_hook.py \
        data/vendor/g5/stock-1008.3/extracted/"M-C5500GGZA-1008.3[C145].img"
"""
from __future__ import annotations
import struct, sys, pathlib
from keystone import Ks, KS_ARCH_SPARC, KS_MODE_BIG_ENDIAN, KS_MODE_SPARC32
from capstone import Cs, CS_ARCH_SPARC, CS_MODE_BIG_ENDIAN
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "tools/mfw/src"))
from mfw import novatek as nv  # noqa: E402

# 1008.3 addresses (VA); file = VA + 0x2E000 in the SPARC code region.
CODE_SHIFT = 0x2E000
CAVE = 0x1E45D4       # dead PDIC stub (0x90 bytes, 0 callers)
GETVCP = 0x1882AC     # SecLibCommon_DdcCmdGetVcp
CALLSITE = 0x103EBC   # the `call DdcCmdGetVcp` inside the dispatcher sub_103DBC
NEW_VERSION = "1010.0"
MAGIC = (0xAD, 0xDE, 0xBE, 0xEF)

ks = Ks(KS_ARCH_SPARC, KS_MODE_SPARC32 | KS_MODE_BIG_ENDIAN)
md = Cs(CS_ARCH_SPARC, CS_MODE_BIG_ENDIAN)
f = lambda va: va + CODE_SHIFT


def _asm(line: str, addr: int) -> bytes:
    enc, _ = ks.asm(line, addr)
    return bytes(enc)


def _call(pc: int, tgt: int) -> bytes:              # keystone mis-encodes SPARC call/branch disp; hand-encode.
    return struct.pack(">I", 0x40000000 | (((tgt - pc) >> 2) & 0x3FFFFFFF))


def _bne(pc: int, tgt: int) -> bytes:               # Bicc bne, a=0, op2=010
    return struct.pack(">I", 0x12800000 | (((tgt - pc) >> 2) & 0x3FFFFF))


def build_cave() -> bytes:
    a = CAVE
    out = b""
    out += _asm("cmp %o0, 0xF2", a); a += 4
    out += _bne(a, GETVCP); a += 4                  # not our code -> branch to the real handler (%o7 preserved)
    out += _asm("nop", a); a += 4
    for val, off in zip(MAGIC, range(4)):
        out += _asm(f"mov {val}, %g1", a); a += 4
        out += _asm("stb %g1, [%o1]" if off == 0 else f"stb %g1, [%o1+{off}]", a); a += 4
    out += _asm("retl", a); a += 4                   # return to %o7+8 = 0x103EC4 (dispatcher's supported-check)
    out += _asm("mov 1, %o0", a); a += 4             # delay slot: return "supported"
    return out


def main(stock_path: str) -> None:
    stock = pathlib.Path(stock_path).read_bytes()
    d = bytearray(stock)
    cave = build_cave()
    assert len(cave) <= 0x90, "hook does not fit the cave"
    d[f(CAVE):f(CAVE) + len(cave)] = cave
    d[f(CALLSITE):f(CALLSITE) + 4] = _call(CALLSITE, CAVE)

    # verify the control flow disassembles to the intended targets
    call_i = next(md.disasm(bytes(d[f(CALLSITE):f(CALLSITE) + 4]), CALLSITE))
    assert call_i.mnemonic == "call" and int(call_i.op_str, 16) == CAVE, call_i.op_str
    assert any(i.mnemonic == "bne" and int(i.op_str, 16) == GETVCP
               for i in md.disasm(bytes(d[f(CAVE):f(CAVE) + len(cave)]), CAVE)), "bne target wrong"

    out, name = nv.restamp(bytes(d), NEW_VERSION, family=b"M-C5500GGZA")
    nv.verify_stock(out, name.filename, family=b"M-C5500GGZA")
    dst = pathlib.Path(stock_path).parent.parent.parent / "builds" / name.filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    changed = sum(1 for i in range(len(stock)) if stock[i] != out[i])
    print(f"built {dst}  ({changed} bytes changed, sum16 {name.tag})")


if __name__ == "__main__":
    main(sys.argv[1])
