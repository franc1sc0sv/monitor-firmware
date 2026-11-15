"""Apply a listing to the prefix and AP body, guarded by per-version expected-byte hashes."""

from __future__ import annotations

import hashlib

from .listing import blocks, parse_rows
from .versions import Version


class GuardError(Exception):
    pass


def _region(v: Version, prefix: bytearray, body: bytearray, addr: int, n: int) -> tuple[bytearray, int]:
    if addr >= v.load_base:
        off = addr - v.load_base
        if off + n > len(body):
            raise GuardError(f"{addr:#x}+{n} is beyond the AP body")
        return body, off
    if v.ram_base <= addr and addr + n <= v.load_base:
        return prefix, addr - v.ram_base
    raise GuardError(f"address {addr:#x} is outside the prefix and the AP body")


def check_guards(v: Version, prefix: bytes, body: bytes, listing: str) -> list[str]:
    """Every listing block must be covered by one guard, and every guard must match the stock image."""
    problems = []
    pre, bod = bytearray(prefix), bytearray(body)
    for g in v.guards:
        buf, off = _region(v, pre, bod, g.at, g.length)
        stock = bytes(buf[off : off + g.length])
        if g.expect_zero and stock != bytes(g.length):
            problems.append(f"guard {g.name} at {g.at:#x}: expected zero padding")
        if g.expect_sha256 and hashlib.sha256(stock).hexdigest() != g.expect_sha256:
            problems.append(f"guard {g.name} at {g.at:#x}: stock bytes differ from version {v.version}")
    for a, data in blocks(parse_rows(listing)):
        if not any(g.at <= a and a + len(data) <= g.at + g.length for g in v.guards):
            problems.append(f"listing block {a:#x}+{len(data)} is not covered by any guard in {v.path.name}")
    return problems


def apply(v: Version, prefix: bytes, body: bytes, listing: str) -> tuple[bytes, bytes, int]:
    problems = check_guards(v, prefix, body, listing)
    if problems:
        raise GuardError("; ".join(problems))
    pre, bod = bytearray(prefix), bytearray(body)
    n = 0
    for a, data in blocks(parse_rows(listing)):
        buf, off = _region(v, pre, bod, a, len(data))
        buf[off : off + len(data)] = data
        n += len(data)
    return bytes(pre), bytes(bod), n
