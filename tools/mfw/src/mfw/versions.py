"""Per-firmware-version facts loaded from firmware/targets/<model>/versions/<version>.toml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tomllib


@dataclass(frozen=True)
class Guard:
    name: str
    at: int
    length: int
    expect_sha256: str | None = None
    expect_zero: bool = False
    note: str = ""


@dataclass(frozen=True)
class Version:
    path: Path
    model: str
    version: str
    ap_sha256: str
    prefix_sha256: str
    descriptor: int
    prefix_len: int
    len_field: int
    tail_limit: int
    ram_base: int
    load_base: int
    flash_write_start: int
    flash_write_end: int
    cave_start: int
    cave_end: int
    symbols: dict[str, int] = field(default_factory=dict)
    guards: tuple[Guard, ...] = ()

    @classmethod
    def load(cls, path: Path) -> Version:
        d = tomllib.loads(path.read_text())
        idn, c, cave = d["identity"], d["container"], d["cave"]
        guards = tuple(
            Guard(g["name"], g["at"], g["len"], g.get("expect_sha256"), g.get("expect_zero", False), g.get("note", ""))
            for g in d.get("guards", [])
        )
        return cls(
            path,
            idn["model"],
            idn["version"],
            idn["ap_sha256"],
            idn["prefix_sha256"],
            c["descriptor"],
            c["prefix_len"],
            c["len_field"],
            c["tail_limit"],
            c["ram_base"],
            c["load_base"],
            c["flash_write_start"],
            c["flash_write_end"],
            cave["start"],
            cave["end"],
            dict(d.get("symbols", {})),
            guards,
        )


def repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "firmware" / "targets").is_dir():
            return parent
    raise FileNotFoundError("firmware/targets not found above " + str(p))


def all_versions(root: Path | None = None) -> list[Version]:
    root = root or repo_root()
    return [Version.load(f) for f in sorted((root / "firmware" / "targets").glob("*/versions/*.toml"))]


def identify(ap_sha256: str, root: Path | None = None) -> Version | None:
    for v in all_versions(root):
        if v.ap_sha256 == ap_sha256:
            return v
    return None
