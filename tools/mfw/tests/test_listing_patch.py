import hashlib
from pathlib import Path

import pytest

from mfw import listing, patch
from mfw.versions import Guard, Version

GOOD = """ram:00200010 98ee ; b.movi r7,0xe
ram:00200012 2c0004 ; b.j 0x200016
ram:00200015 00 ; .bytes 00
---- labels
---- disassembly check
00200010  b.movi r7,0xe
00200012  b.j 0x00200016
---- encoding notes
"""


def test_parse_and_blocks():
    rows = listing.parse_rows(GOOD)
    assert [r.addr for r in rows] == [0x200010, 0x200012, 0x200015]
    assert listing.blocks(rows) == [(0x200010, bytes.fromhex("98ee2c000400"))]


def test_checker_accepts_external_target():
    assert listing.check(GOOD, {0x200016}) == []


def test_checker_rejects_branch_into_nowhere():
    assert any("targets" in p for p in listing.check(GOOD, set()))


def test_checker_rejects_text_mismatch():
    bad = GOOD.replace("00200010  b.movi r7,0xe", "00200010  b.movi r7,0xf   <-- differs from source: b.movi r7,0xe")
    assert any("text differs" in p for p in listing.check(bad, {0x200016}))


def test_checker_rejects_overlap():
    bad = GOOD.replace("ram:00200015 00 ; .bytes 00", "ram:00200014 0000 ; .bytes 0000")
    assert any("overlap" in p for p in listing.check(bad, {0x200016}))


def _version(prefix: bytes, guards) -> Version:
    return Version(
        Path("test.toml"),
        "TEST",
        "0.0",
        "",
        "",
        0,
        0x20,
        0,
        0,
        0x200000,
        0x200020,
        0,
        0,
        0x200040,
        0x200080,
        {},
        tuple(guards),
    )


def test_guarded_apply_and_refusals():
    prefix = bytes(range(0x20))
    body = bytes(0x100)
    stock = prefix[0x10:0x16]
    g = Guard("site", 0x200010, 6, expect_sha256=hashlib.sha256(stock).hexdigest())
    v = _version(prefix, [g])
    pre2, body2, n = patch.apply(v, prefix, body, GOOD)
    assert n == 6 and pre2[0x10:0x16] == bytes.fromhex("98ee2c000400") and body2 == body

    other = bytearray(prefix)
    other[0x10] ^= 1  # a different firmware version: stock bytes do not match
    with pytest.raises(patch.GuardError, match="stock bytes differ"):
        patch.apply(v, bytes(other), body, GOOD)

    with pytest.raises(patch.GuardError, match="not covered"):
        patch.apply(_version(prefix, []), prefix, body, GOOD)


def test_real_version_files_load():
    from mfw.versions import all_versions

    vs = all_versions()
    assert any(v.model == "LC34G55T" and v.version == "1006.0" for v in vs)
    for v in vs:
        assert v.guards, f"{v.path} has no guards"
        assert v.cave_start < v.cave_end
