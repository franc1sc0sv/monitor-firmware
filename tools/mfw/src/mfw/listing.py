"""Assembler listings (output of tools/ghidra/AsmPatch2.java) and the independent listing checker."""

from __future__ import annotations

import re
from dataclasses import dataclass

BRANCHES = (
    "b.j",
    "b.jal",
    "b.bf",
    "b.bnf",
    "b.beq",
    "b.bne",
    "b.beqi",
    "b.bnei",
    "b.bgtui",
    "b.bleui",
    "b.bgtu",
    "b.bleu",
)
_ROW = re.compile(r"ram:([0-9a-f]+) ([0-9a-f]+) ; (.*)")


@dataclass(frozen=True)
class Row:
    addr: int
    data: bytes
    text: str


def parse_rows(listing: str) -> list[Row]:
    rows = []
    for line in listing.split("---- labels")[0].splitlines():
        m = _ROW.match(line)
        if m:
            rows.append(Row(int(m.group(1), 16), bytes.fromhex(m.group(2)), m.group(3)))
    return rows


def blocks(rows: list[Row]) -> list[tuple[int, bytes]]:
    """Merges contiguous rows into (start address, bytes) blocks."""
    out: list[list] = []
    for r in rows:
        if out and out[-1][0] + len(out[-1][1]) == r.addr:
            out[-1][1] += r.data
        else:
            out.append([r.addr, bytearray(r.data)])
    return [(a, bytes(b)) for a, b in out]


def check(listing: str, external: set[int], cave: tuple[int, int] | None = None) -> list[str]:
    """Independent checks: no overlaps, every branch target is an instruction start or an allowed external,
    disassembly text matches the source, code inside the cave stays inside it."""
    problems = []
    rows = parse_rows(listing)
    starts = {r.addr for r in rows}
    seen: dict[int, int] = {}
    for r in rows:
        for a in range(r.addr, r.addr + len(r.data)):
            if a in seen:
                problems.append(f"overlap at {a:#x}")
                break
            seen[a] = r.addr
        if cave and cave[0] <= r.addr < cave[1] and r.addr + len(r.data) > cave[1]:
            problems.append(f"code crosses the cave end at {r.addr:#x}")
    if "---- disassembly check" in listing:
        dis = listing.split("---- disassembly check")[1].split("---- encoding notes")[0]
        for line in dis.splitlines():
            m = re.match(r"([0-9a-f]{8})\s+(\S+)\s*(.*?)\s*(<--.*)?$", line)
            if not m:
                continue
            addr, mn, ops, flag = int(m.group(1), 16), m.group(2), m.group(3), m.group(4)
            if flag:
                problems.append(f"text differs at {addr:#x}: {line.strip()}")
            if mn in BRANCHES:
                t = int(ops.split(",")[-1], 16)
                if t not in starts and t not in external:
                    problems.append(f"branch at {addr:#x} ({mn} {ops}) targets {t:#x}, not an instruction start")
    return problems
