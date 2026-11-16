#!/usr/bin/env python3
"""Plan a G5 flash over DDC with the 1021.4+ SRAM sector job.

Given the image to install, the image currently in the INACTIVE bank (destination) and the image in the ACTIVE bank
(used as the page source, because the destination sector is erased first), emit a PowerShell script that runs one
sector job per changed 4 KB sector and finally rewrites the activation sector 0x7000 (descriptor B + tag byte).

    uv run python tools/g5/ddc_flash_plan.py --target NEW.img --dest-image OLD_INACTIVE.img \
        --source-image ACTIVE.img --dest-bank A|B --sector7000 out/g5-flash-7000.bin --out out/g5-ddc-flash.ps1

Bank A records live at their container address, bank B at +0x400000. Tag byte (flash 0x7FFF) 0xAA boots bank B,
anything else boots bank A.
"""
from __future__ import annotations
import argparse, struct

SHARED = (0x0, 0x6000)              # boot record and descriptor A: never written by the DDC flasher
XIP = lambda f: (f - 0x108000) % 0x800000


def records(path: str) -> dict[int, bytes]:
    d = open(path, "rb").read(); out = {}; i = 0x20
    while i + 32 <= len(d):
        f0, f1, size, _, mag = struct.unpack(">HHIII", d[i:i + 16])
        if mag != 0x04000000 or size == 0 or i + 32 + size > len(d):
            break
        out[(f0 << 16) | f1] = d[i + 32:i + 32 + size]; i += 32 + size
    return out


def bank_bytes(recs: dict[int, bytes], off: int) -> dict[int, int]:
    """flash-relative-to-bank byte map (only record bytes)."""
    m = {}
    for dest, data in recs.items():
        if dest in SHARED:
            continue
        for i, b in enumerate(data):
            m[dest + off + i] = b
    return m


def runs_of(want: bytes, have: bytes) -> list[tuple[int, bytes]]:
    runs, i = [], 0
    while i < len(want):
        if want[i] == have[i]:
            i += 1; continue
        j = i
        while j < len(want) and (want[j] != have[j] or (j + 1 < len(want) and want[j + 1] != have[j + 1])):
            j += 1
        runs.append((i, want[i:j])); i = j
    return runs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True); ap.add_argument("--dest-image", required=True)
    ap.add_argument("--source-image", required=True); ap.add_argument("--dest-bank", choices="AB", required=True)
    ap.add_argument("--sector7000", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    doff = 0x400000 if a.dest_bank == "B" else 0
    soff = 0x400000 - doff
    tgt = bank_bytes(records(a.target), doff)
    cur = bank_bytes(records(a.dest_image), doff)
    src = bank_bytes(records(a.source_image), soff)
    sectors = sorted({f & ~0xFFF for f, b in tgt.items() if cur.get(f, 0xFF) != b})
    jobs = []
    for s in sectors:
        want = bytes(tgt.get(s + i, cur.get(s + i, 0xFF)) for i in range(0x1000))
        srcsec = s - doff + soff
        have = bytes(src.get(srcsec + i, 0xFF) for i in range(0x1000))
        r = runs_of(want, have)
        jobs.append((s, XIP(srcsec), r, sum(len(d) for _, d in r)))
    sec7 = bytearray(open(a.sector7000, "rb").read()); assert len(sec7) == 0x1000
    sec7[0xFFF] = 0xAA if a.dest_bank == "B" else 0x00
    act = runs_of(bytes(sec7), b"\xff" * 0x1000)
    ps = ["param([switch]$Activate)",
          ". '\\\\wsl.localhost\\Ubuntu-24.04\\home\\francisco\\projects\\personal-projects\\monitor-firmware\\tools\\windows\\experiments\\g5\\g5-ddc.ps1'",
          ". '\\\\wsl.localhost\\Ubuntu-24.04\\home\\francisco\\projects\\personal-projects\\monitor-firmware\\tools\\windows\\experiments\\g5\\g5-final.ps1'",
          ". '\\\\wsl.localhost\\Ubuntu-24.04\\home\\francisco\\projects\\personal-projects\\monitor-firmware\\tools\\windows\\experiments\\g5\\g5-sector.ps1'",
          "$t0 = Get-Date; function Log($m) { '{0,6:N1}s {1}' -f ((Get-Date) - $t0).TotalSeconds, $m }"]

    def job_ps(dst: int, srcva: int, runs: list[tuple[int, bytes]], label: str) -> list[str]:
        blob = bytearray()
        for off, data in runs:
            blob += struct.pack(">HH", off, len(data)) + data
            blob += b"\0" * (-len(blob) % 4)
        hexs = blob.hex()
        return [f"$r = SectorJob ([UInt32]0x{dst:X}) ([UInt32]0x{srcva:X}) {len(runs)} '{hexs}'",
                f"Log ('{label}: mismatching words = {{0}}' -f $r); if ($r -ne 0) {{ throw 'sector verify failed' }}"]
    for s, sva, r, n in jobs:
        ps += job_ps(s, sva, r, f"sector 0x{s:06X} ({len(r)} runs, {n} B)")
    ps += ["if (-not $Activate) { Log 'bank written and verified; run with -Activate to switch'; return }"]
    ps += job_ps(0x7000, 0, act, f"activation sector (tag 0x{sec7[0xFFF]:02X})")
    ps += ["Log 'activated; rebooting the monitor into the new bank'", "Reboot51"]
    open(a.out, "w", newline="\r\n").write("\n".join(ps) + "\n")
    print(f"{len(jobs)} sectors: " + ", ".join(f"0x{s:06X}({n}B)" for s, _, _, n in jobs) + f"; activation {sum(len(d) for _, d in act)}B -> {a.out}")


if __name__ == "__main__":
    main()
