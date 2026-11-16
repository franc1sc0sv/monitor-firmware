#!/usr/bin/env python3
"""Build a SPARC 'mailbox script runner' for the 1021.0 hook and emit a PowerShell file that uploads and runs it.

The runner (uploaded at 0xA803C400) walks a table of 4-byte entries (cmd, b1, b2, b3; cmd 0 ends) and calls the HAL
mailbox for each one back to back (mode 2 = handshake for cmd 0x12 read, mode 1 otherwise); after every entry it waits a short loop and stores the mailbox reply word (+0xB4)
into an output array. With the patched 8051 (cmd 0x21 POKE, cmd 0x03 PEEK) this runs an 8051 register sequence at
full speed, which DDC-paced POKEs cannot (~1 s each).

    uv run --with keystone-engine python tools/g5/mbox_script.py <out.ps1> <cmd> <b1> <b2> <b3> [...]
"""
from __future__ import annotations
import sys
from keystone import Ks, KS_ARCH_SPARC, KS_MODE_BIG_ENDIAN, KS_MODE_SPARC32

CODE, TBL, OUT = 0xA803C400, 0xA803C600, 0xA803C800
HALMBOX, REPLY = 0xA002F220, 0x9F0A01B4
hi = lambda a: (a >> 10) & 0x3FFFFF
lo = lambda a: a & 0x3FF

SRC = f"""
    save %sp, -0x60, %sp
    sethi {hi(TBL)}, %l0
    or %l0, {lo(TBL)}, %l0
    sethi {hi(OUT)}, %l1
    or %l1, {lo(OUT)}, %l1
loop:
    ldub [%l0], %o0
    cmp %o0, 0
    be done
    nop
    ldub [%l0+1], %o1
    ldub [%l0+2], %o2
    ldub [%l0+3], %o3
    mov 1, %o4
    cmp %o0, 0x12
    bne m1
    nop
    mov 2, %o4
m1:
    sethi {hi(HALMBOX)}, %g1
    or %g1, {lo(HALMBOX)}, %g1
    jmpl %g1, %o7
    nop
    sethi 0x40, %l2
dly:
    subcc %l2, 1, %l2
    bne dly
    nop
    sethi {hi(REPLY)}, %g1
    or %g1, {lo(REPLY)}, %g1
    ld [%g1], %l3
    st %l3, [%l1]
    add %l1, 4, %l1
    add %l0, 4, %l0
    ba loop
    nop
done:
    ret
    restore
"""


def assemble() -> bytes:
    ks = Ks(KS_ARCH_SPARC, KS_MODE_SPARC32 | KS_MODE_BIG_ENDIAN)
    enc, _ = ks.asm(SRC, CODE)
    return bytes(enc)


def main() -> None:
    out = sys.argv[1]
    vals = [int(x, 16) for x in sys.argv[2:]]
    assert len(vals) % 4 == 0 and len(vals) // 4 <= 120
    table = bytes(vals) + b"\0\0\0\0"
    code = assemble()
    assert CODE + len(code) <= TBL
    n = len(vals) // 4
    hexs = lambda b: ",".join(f"0x{x:02X}" for x in b)
    lines = [
        ". '\\\\wsl.localhost\\Ubuntu-24.04\\home\\francisco\\projects\\personal-projects\\monitor-firmware\\tools\\windows\\experiments\\g5\\g5-ddc.ps1'",
        ". '\\\\wsl.localhost\\Ubuntu-24.04\\home\\francisco\\projects\\personal-projects\\monitor-firmware\\tools\\windows\\experiments\\g5\\g5-final.ps1'",
        f"Up ([Convert]::ToUInt32('{CODE:08X}',16)) ([byte[]]({hexs(code)}))",
        f"Up ([Convert]::ToUInt32('{TBL:08X}',16)) ([byte[]]({hexs(table)}))",
        f"$r = Call ([Convert]::ToUInt32('{CODE:08X}',16)) @()",
        "Start-Sleep -Milliseconds 500",
        f"for ($i = 0; $i -lt {n}; $i++) {{ '{{0,3}} {{1:X8}}' -f $i, (RdWF ([UInt32]([Convert]::ToUInt32('{OUT:08X}',16) + 4*$i))) }}",
    ]
    open(out, "w", newline="\r\n").write("\n".join(lines) + "\n")
    print(f"runner {len(code)}B, {n} entries -> {out}")


if __name__ == "__main__":
    main()
