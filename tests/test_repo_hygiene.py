"""Fails if vendor binaries, large files or serial numbers would be published (see docs/legal.md)."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True)
    return [ROOT / p for p in out.stdout.splitlines() if (ROOT / p).is_file()]


def test_no_binaries_or_large_files():
    bad = [p for p in tracked() if p.suffix.lower() in {".bin", ".img", ".gpr", ".rep"} or p.stat().st_size > 200_000]
    assert not bad, f"binary or large files tracked: {bad}"


def test_no_device_serial_numbers():
    pattern = re.compile(rb"HNTX\d{6}[A-Z0-9]{4}")  # Samsung panel serial format seen on this unit
    hits = [p for p in tracked() if pattern.search(p.read_bytes())]
    assert not hits, f"serial number found in {hits}"


def test_no_vendor_data_dirs_tracked():
    assert not [p for p in tracked() if p.relative_to(ROOT).parts[0] in {"data", "out"}]
