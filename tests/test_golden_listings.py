"""CI-safe checks on committed golden listings (no vendor data needed)."""

from pathlib import Path

import pytest

from mfw import listing
from mfw.versions import all_versions

ROOT = Path(__file__).resolve().parents[1]
LISTINGS = sorted(ROOT.glob("firmware/targets/*/listings/*/*.lst"))


@pytest.mark.parametrize("path", LISTINGS, ids=[p.name for p in LISTINGS])
def test_golden_listing_is_consistent(path):
    v = next(v for v in all_versions() if v.version == path.parent.name)
    assert listing.check(path.read_text(), set(v.symbols.values()), (v.cave_start, v.cave_end)) == []


@pytest.mark.parametrize("path", LISTINGS, ids=[p.name for p in LISTINGS])
def test_every_block_is_guarded(path):
    v = next(v for v in all_versions() if v.version == path.parent.name)
    for a, data in listing.blocks(listing.parse_rows(path.read_text())):
        assert any(g.at <= a and a + len(data) <= g.at + g.length for g in v.guards), f"block {a:#x} unguarded"
