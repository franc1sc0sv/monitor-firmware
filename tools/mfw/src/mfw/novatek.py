"""Novatek NVTSC_IMG firmware package (Samsung Odyssey G5 "FALCON", scaler NT68xxx).

A different platform from the MStar MST9U container in `container.py`: the Odyssey G5 ships a
`\\x7fNVTSC_IMG` package flashed over USB, gated by the monitor's updater on two reproducible checks
(see docs/targets/g5-falcon/overview.md):

  * a strict embedded/filename version in the form ``M-C5500GGZA-NNNN.N``;
  * a whole-file 16-bit byte-sum, printed as the four hex digits in ``[XXXX]`` in the file name.

This module provides the model-independent primitives needed to verify a stock image and to re-stamp
a modified one so the updater still accepts it. It never contains or ships vendor bytes: the stock
image stays under the gitignored ``data/vendor/g5/``.

Confirmed against the official ``M-C5500GGZA-1008.3[C145].img`` (3,449,760 bytes, sum16 == 0xC145).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAGIC = b"\x7fNVTSC_IMG\n"

# Embedded id form: "<family>-<NNNN.N>", e.g. "M-C5500GGZA-1008.3". The family is fixed per model.
_ID_RE = re.compile(rb"(?P<family>[A-Z0-9-]+?)-(?P<version>\d{4}\.\d)")
# File name form: "<family>-<NNNN.N>[XXXX].img" (XXXX = sum16, upper-case hex).
_NAME_RE = re.compile(r"^(?P<family>[A-Za-z0-9-]+?)-(?P<version>\d{4}\.\d)\[(?P<tag>[0-9A-Fa-f]{4})\]\.img$")


class NovatekError(Exception):
    pass


def sum16(data: bytes) -> int:
    """The updater's whole-file integrity value: low 16 bits of the sum of every byte."""
    return sum(data) & 0xFFFF


def tag(data: bytes) -> str:
    """sum16 rendered as the 4 upper-case hex digits that go in the file name's ``[..]``."""
    return f"{sum16(data):04X}"


@dataclass(frozen=True)
class ImageName:
    family: str
    version: str
    tag: str

    @property
    def filename(self) -> str:
        return f"{self.family}-{self.version}[{self.tag}].img"


def parse_filename(name: str) -> ImageName:
    m = _NAME_RE.match(name.strip())
    if not m:
        raise NovatekError(f"not a Novatek image file name: {name!r}")
    return ImageName(m.group("family"), m.group("version"), m.group("tag").upper())


@dataclass(frozen=True)
class EmbeddedId:
    offset: int
    family: str
    version: str

    @property
    def text(self) -> str:
        return f"{self.family}-{self.version}"


def find_embedded_id(data: bytes, family: bytes | None = None) -> EmbeddedId:
    """Locate the embedded ``<family>-<NNNN.N>`` string. If *family* is given, require that family."""
    for m in _ID_RE.finditer(data):
        fam = m.group("family")
        if family is not None and fam != family:
            continue
        return EmbeddedId(m.start(), fam.decode("ascii"), m.group("version").decode("ascii"))
    raise NovatekError("no embedded version id found")


def has_magic(data: bytes) -> bool:
    return data.startswith(MAGIC)


@dataclass(frozen=True)
class Identify:
    size: int
    magic: bool
    sum16: int
    tag: str
    embedded: EmbeddedId


def identify(data: bytes, family: bytes | None = None) -> Identify:
    """Read-only summary of a Novatek image (no vendor bytes retained)."""
    return Identify(
        size=len(data),
        magic=has_magic(data),
        sum16=sum16(data),
        tag=tag(data),
        embedded=find_embedded_id(data, family),
    )


def verify_stock(data: bytes, filename: str, *, family: bytes | None = None) -> Identify:
    """Check a stock image against its own file name: magic, matching version, and sum16 == the name tag."""
    name = parse_filename(filename)
    info = identify(data, family)
    if not info.magic:
        raise NovatekError("missing NVTSC_IMG magic")
    if info.tag != name.tag:
        raise NovatekError(f"sum16 {info.tag} != file-name tag {name.tag}")
    if info.embedded.version != name.version:
        raise NovatekError(f"embedded version {info.embedded.version} != file-name version {name.version}")
    return info


def restamp(data: bytes, new_version: str, *, family: bytes | None = None) -> tuple[bytes, ImageName]:
    """Return *data* with the embedded version replaced by *new_version* (same length) and the new file name.

    Only the ``NNNN.N`` digits are overwritten, in place, so the image length never changes. The returned
    :class:`ImageName` carries the recomputed sum16 tag, so the file the updater sees stays self-consistent.
    Raises if *new_version* is not the ``NNNN.N`` shape or would change the embedded string length.
    """
    if not re.fullmatch(r"\d{4}\.\d", new_version):
        raise NovatekError(f"version must be NNNN.N, got {new_version!r}")
    emb = find_embedded_id(data, family)
    if len(new_version) != len(emb.version):
        raise NovatekError("new version changes the embedded string length")
    start = emb.offset + len(emb.family) + 1  # skip "<family>-"
    out = bytearray(data)
    out[start : start + len(new_version)] = new_version.encode("ascii")
    out = bytes(out)
    return out, ImageName(emb.family, new_version, tag(out))
