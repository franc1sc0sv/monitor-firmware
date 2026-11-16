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

VERSION = "1021.4"
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


F6B3_CMP, F6C9_CMP = 0xF6BE, 0xF6CD                  # CJNE A,#0x1A in the flash-op prologue / epilogue


def patch_8051(d: bytearray) -> None:
    def at(addr: int) -> int: return SEGA_DATA + addr
    assert bytes(d[at(POKE_AT):at(POKE_AT) + len(STOCK_EAAB)]) == STOCK_EAAB, "unexpected bytes at 0xEAAB"
    assert bytes(d[at(SLOT03):at(SLOT03) + 3]) == bytes.fromhex("022BBC"), "cmd 0x03 slot is not the stock ack"
    assert bytes(d[at(0x29AF):at(0x29AF) + 3]) == bytes.fromhex("12EAAB"), "cmd 0x21 handler does not call 0xEAAB"
    d[at(POKE_AT):at(POKE_AT) + 16] = POKE
    d[at(PEEK_AT):at(PEEK_AT) + 37] = PEEK
    d[at(SLOT03):at(SLOT03) + 3] = bytes([0x02, PEEK_AT >> 8, PEEK_AT & 0xFF])
    # 1021.4: the prologue/epilogue clear/set XDATA F1A8 bit0 when D511 == 0x1A (this chip); setting it resets the
    # whole chip after every flash op. Compare against 0xFF instead (D511 is a read-only 0x1A): F1A8 is left alone,
    # the F1DF bus grant/release is kept.
    for cmp_at in (F6B3_CMP, F6C9_CMP):
        assert bytes(d[at(cmp_at):at(cmp_at) + 2]) == bytes.fromhex("B41A"), hex(cmp_at)
        d[at(cmp_at) + 1] = 0xFF
    f0, f1, size, _ = struct.unpack(">HHII", d[SEGA_HDR:SEGA_HDR + 12])
    assert (f0, f1, size) == (1, 0, 0xFAC0)
    d[SEGA_HDR + 8:SEGA_HDR + 12] = struct.pack(">I", sum(d[SEGA_DATA:SEGA_DATA + size]) & 0xFFFF)


# ---- HAL SRAM flash worker (record @0x23CC0: flash 0x0D0000, loaded to SRAM 0xA0028000, sum16 checksum) ----
HAL_HDR, HAL_DATA, HAL_SIZE, SRAM = 0x23CC0, 0x23CE0, 0x7760, 0xA0028000
CRASH, CRASH_END = 0xA002D6B8, 0xA002E344          # "System Crash, PC" reporter; entry kept (exception vector)
CRASH_HEAD = bytes.fromhex("9de3bf881b0007e7c24b60d880a06000")
WORKER = CRASH + 8
WLIST = 0xA803CA00                                  # worker list (BSS upload window), 24-byte entries
WORKER_SRC = f"""
    save %sp, -0x60, %sp
    rd %psr, %l7
    or %l7, 0xf00, %l6
    wr %l6, %g0, %psr
    nop
    nop
    nop
    sethi {_hi(WLIST)}, %l0
    or %l0, {WLIST & 0x3FF}, %l0
    sethi {_hi(0xA0028000)}, %l1
    sethi {_hi(0xA0031000)}, %l2
wl:
    ld [%l0], %g1
    cmp %g1, 0
    be wdone
    nop
    cmp %g1, 1
    bne wchk
    nop
    ld [%l0+4], %l3
wdly:
    subcc %l3, 1, %l3
    bne wdly
    nop
    ba wnext
    mov 0, %o0
wchk:
    cmp %g1, %l1
    blu wdone
    nop
    cmp %g1, %l2
    bgeu wdone
    nop
    ld [%l0+4], %o0
    ld [%l0+8], %o1
    ld [%l0+0xc], %o2
    ld [%l0+0x10], %o3
    ld [%l0+0x14], %o4
    jmpl %g1, %o7
    nop
wnext:
    st %o0, [%l0]
    add %l0, 24, %l0
    ba wl
    nop
wdone:
    wr %l7, %g0, %psr
    nop
    nop
    nop
    ret
    restore %g0, 1, %o0
"""


JOB, PBUF = 0xA803CA00, 0xA803C400                  # sector-job struct / page buffer (BSS upload window)
HALMBOX, PREP, PUSH = 0xA002F220, 0x00150D08, 0x0015FEBC   # runtime addresses
SET = lambda reg, v: f"sethi {_hi(v)}, {reg}\n    or {reg}, {v & 0x3FF}, {reg}"
PIL_ON = "rd %psr, %l7\n    or %l7, 0xf00, %g1\n    wr %g1, %g0, %psr\n    nop\n    nop\n    nop"
PIL_OFF = "wr %l7, %g0, %psr\n    nop\n    nop\n    nop"
def HAL(o0, o1, o2, o3, o4):
    return f"""mov {o0}, %o0
    mov {o1}, %o1
    mov {o2}, %o2
    mov {o3}, %o3
    mov {o4}, %o4
    {SET('%g1', HALMBOX)}
    jmpl %g1, %o7
    nop"""
# job: +0 dst flash (4 KB aligned; must be in the INACTIVE bank - tag byte flash 0x7FFF == 0xAA means bank B is
# active, so only [0x8000,0x400000) is allowed, else only [0x400000,0x800000) - or the activation sector 0x7000), +4 src VA of the page source (0 = 0xFF),
# +8 run count, +12 runs {u16 off, u16 len, data[len], pad to 4}. Erases dst, programs the 16 pages built from
# src+runs (all-FF pages skipped), flushes, verifies against the XIP view and returns the mismatching word count
# (-1 = refused). The 8051 ops run with PIL 15 (no flash fetches while the 8051 owns the SPI bus).
SECJOB_SRC = f"""
    save %sp, -0x70, %sp
    {SET('%l0', JOB)}
    ld [%l0], %l1
    and %l1, 0xfff, %g1
    cmp %g1, 0
    bne jfail
    nop
    sethi {_hi(0x7000)}, %g1
    cmp %l1, %g1
    be jok
    nop
    {SET('%g1', 0x6FFFFC)}
    ld [%g1], %g1
    and %g1, 0xff, %g1
    cmp %g1, 0xaa
    be jact_b
    nop
    srl %l1, 22, %g1
    cmp %g1, 1
    be jok
    nop
    ba jfail
    nop
jact_b:
    srl %l1, 22, %g1
    cmp %g1, 0
    bne jfail
    nop
    sethi {_hi(0x8000)}, %g1
    cmp %l1, %g1
    blu jfail
    nop
jok:
    ld [%l0+4], %l2
    ld [%l0+8], %l3
    add %l0, 12, %l4
    {SET('%l6', PBUF)}
    {SET('%g1', 0x108000)}
    sub %l1, %g1, %i2
    {SET('%g1', 0x7FFFFF)}
    and %i2, %g1, %i2
    {SET('%g1', PREP)}
    jmpl %g1, %o7
    nop
    srl %l1, 24, %i3
    {HAL(0x21, 0xA7, 0x57, '%i3', 1)}
    srl %l1, 16, %i3
    and %i3, 0xff, %i3
    {HAL(0x21, 0xA7, 0x58, '%i3', 1)}
    {HAL(0x21, 0xA7, 0x59, 0, 1)}
    {HAL(0x21, 0xA7, 0x5A, 0, 1)}
    srl %l1, 8, %i3
    and %i3, 0xff, %i3
    {HAL(0x14, 1, '%i3', 0, 1)}
    {PIL_ON}
    {HAL(0x13, 0, 0, 0, 2)}
    {PIL_OFF}
    mov 0, %l5
jpg:
    call jbuild
    nop
    mov %l6, %g2
    mov 64, %g3
jff:
    ld [%g2], %g4
    cmp %g4, -1
    bne jprog
    nop
    add %g2, 4, %g2
    subcc %g3, 1, %g3
    bne jff
    nop
    ba jnext
    nop
jprog:
    mov 0, %o0
    mov 256, %o1
    mov %l6, %o2
    {SET('%g1', PUSH)}
    jmpl %g1, %o7
    nop
    sll %l5, 8, %i3
    add %l1, %i3, %i3
    srl %i3, 8, %i3
    and %i3, 0xff, %i3
    {HAL(0x14, 1, '%i3', 0, 1)}
    {PIL_ON}
    {HAL(0x11, 0, 0, 0, 2)}
    {PIL_OFF}
jnext:
    add %l5, 1, %l5
    cmp %l5, 16
    bl jpg
    nop
    flush %g0
    mov 0, %i1
    mov 0, %l5
jvp:
    call jbuild
    nop
    sll %l5, 8, %g1
    add %i2, %g1, %g1
    mov %l6, %g2
    mov 64, %g3
jvl:
    ld [%g1], %g4
    ld [%g2], %g5
    cmp %g4, %g5
    be jvn
    nop
    add %i1, 1, %i1
jvn:
    add %g1, 4, %g1
    add %g2, 4, %g2
    subcc %g3, 1, %g3
    bne jvl
    nop
    add %l5, 1, %l5
    cmp %l5, 16
    bl jvp
    nop
    ret
    restore %i1, 0, %o0
jfail:
    ret
    restore %g0, -1, %o0
jbuild:
    sll %l5, 8, %g1
    mov %l6, %g2
    mov 64, %g3
    cmp %l2, 0
    be jbff
    nop
    add %l2, %g1, %g1
jbc:
    ld [%g1], %g4
    st %g4, [%g2]
    add %g1, 4, %g1
    add %g2, 4, %g2
    subcc %g3, 1, %g3
    bne jbc
    nop
    ba jbp
    nop
jbff:
    mov -1, %g4
jbf1:
    st %g4, [%g2]
    add %g2, 4, %g2
    subcc %g3, 1, %g3
    bne jbf1
    nop
jbp:
    mov %l4, %g1
    mov %l3, %g2
jbr:
    cmp %g2, 0
    be jbret
    nop
    lduh [%g1], %g3
    lduh [%g1+2], %g4
    add %g1, 4, %o0
    mov 0, %o1
jbk:
    cmp %o1, %g4
    be jbkd
    nop
    add %g3, %o1, %o2
    srl %o2, 8, %o3
    cmp %o3, %l5
    bne jbkn
    nop
    and %o2, 0xff, %o2
    ldub [%o0+%o1], %o3
    stb %o3, [%l6+%o2]
jbkn:
    ba jbk
    add %o1, 1, %o1
jbkd:
    add %g4, 3, %o2
    andn %o2, 3, %o2
    add %o2, 4, %o2
    add %g1, %o2, %g1
    ba jbr
    sub %g2, 1, %g2
jbret:
    retl
    nop
"""


def build_worker() -> bytes:
    from keystone import Ks, KS_ARCH_SPARC, KS_MODE_BIG_ENDIAN, KS_MODE_SPARC32
    ks = Ks(KS_ARCH_SPARC, KS_MODE_SPARC32 | KS_MODE_BIG_ENDIAN)
    stub, _ = ks.asm(f"ba {CRASH}\nnop", CRASH)            # crash entry: spin in SRAM until the watchdog resets
    stub = bytes(stub)
    assert stub == bytes.fromhex("1080000001000000"), stub.hex()
    body, _ = ks.asm(WORKER_SRC, WORKER)
    code = stub + bytes(body)
    global SECJOB
    SECJOB = (CRASH + len(code) + 7) & ~7
    code += b"\x01\x00\x00\x00" * ((SECJOB - CRASH - len(code)) // 4)
    job, _ = ks.asm(SECJOB_SRC, SECJOB)
    return code + bytes(job)


def patch_hal(d: bytearray) -> int:
    f0, f1, size, _ = struct.unpack(">HHII", d[HAL_HDR:HAL_HDR + 12])
    assert (f0, f1, size) == (0x0D, 0, HAL_SIZE), "unexpected HAL record header"
    at = HAL_DATA + (CRASH - SRAM)
    assert bytes(d[at:at + 16]) == CRASH_HEAD, "unexpected bytes at the crash reporter"
    code = build_worker()
    assert CRASH + len(code) <= CRASH_END
    d[at:at + len(code)] = code
    d[HAL_HDR + 8:HAL_HDR + 12] = struct.pack(">I", sum(d[HAL_DATA:HAL_DATA + size]) & 0xFFFF)
    return len(code)


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
    wlen = patch_hal(d)
    out, name = nv.restamp(bytes(d), version, family=b"M-C5500GGZA")
    nv.verify_stock(out, name.filename, family=b"M-C5500GGZA")
    dst = pathlib.Path(stock_path).parent.parent.parent / "builds" / name.filename
    dst.write_bytes(out)
    diff = [i for i in range(len(stock)) if stock[i] != out[i]]
    in8051 = [i for i in diff if SEGA_HDR <= i < SEGA_DATA + 0xFAC0]
    print(f"built {dst}  hook {len(code)}B, {len(diff)} bytes changed ({len(in8051)} in the 8051 record), sum16 {name.tag}")
    print(f"  HAL code {wlen}B at SRAM {hex(CRASH)} (entry stub) / {hex(WORKER)} (worker, list {hex(WLIST)}) / {hex(SECJOB)} (sector job {hex(JOB)})")
    print(f"  8051 changed offsets: {hex(min(in8051))}..{hex(max(in8051))}  GET={hex(get_entry)} SET={hex(set_entry)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
