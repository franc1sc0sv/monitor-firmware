"""MST9U flash container: parse, verify, and rebuild with a new AP body.

Layout (LC34G55T 1006.0, see docs/hardware/mst9u-container.md):
  descriptor  u32 LE x10: ap_flash_start, ram_start, ram_end, ap_flash_end, 0, hdr_crc32, 0, 0, filesize-4, self
  prefix      prefix_len uncompressed bytes at ap_flash_start (loads at ram_base); prefix+len_field = region length
  stream      raw DEFLATE of the AP body (loads at load_base), then u32 LE decompressed size and an u16 check word
  trailer     CRC-32 (big-endian) at filesize-4 over [0, filesize-4)
Stage 2 of the boot loader inflates without checking the u16 or any CRC; we still keep every CRC consistent.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass

from .crc import crc32_msb


class ContainerError(Exception):
    pass


@dataclass
class Layout:
    descriptor: int = 0x11000
    prefix_len: int = 0x3800
    len_field: int = 0x114A
    tail_limit: int = 0x160930


@dataclass
class Parsed:
    desc: list[int]
    fstart: int
    fend: int
    sstart: int
    send: int
    size: int
    check: int
    hdr_crc: int
    fsz4: int


def parse(img: bytes, lay: Layout) -> Parsed:
    d = list(struct.unpack_from("<10I", img, lay.descriptor))
    fstart, fend = d[0], d[3]
    sstart, send = fstart + lay.prefix_len, fend - 6
    if not (0 < fstart < sstart < send < fend <= len(img)):
        raise ContainerError(f"descriptor out of range: {[hex(x) for x in d]}")
    size, check = struct.unpack_from("<IH", img, send)
    return Parsed(d, fstart, fend, sstart, send, size, check, d[5], d[8])


def unpack(img: bytes, lay: Layout) -> tuple[bytes, bytes]:
    """Returns (prefix, ap_body)."""
    p = parse(img, lay)
    body = zlib.decompressobj(-15).decompress(img[p.sstart : p.send])
    if len(body) != p.size:
        raise ContainerError(f"inflated size {len(body):#x} != recorded {p.size:#x}")
    return img[p.fstart : p.sstart], body


def verify(img: bytes, lay: Layout) -> list[str]:
    """Returns a list of problems (empty when the image is consistent)."""
    problems = []
    p = parse(img, lay)
    try:
        unpack(img, lay)
    except (ContainerError, zlib.error) as e:
        problems.append(f"stream: {e}")
    if crc32_msb(img[p.fstart : p.fend]) != p.hdr_crc:
        problems.append("header CRC-32 mismatch")
    if crc32_msb(img[: p.fsz4]) != struct.unpack_from(">I", img, p.fsz4)[0]:
        problems.append("trailer CRC-32 mismatch")
    if struct.unpack_from("<I", img, p.fstart + lay.len_field)[0] != p.fend - p.fstart:
        problems.append("prefix length field mismatch")
    if p.desc[2] - p.desc[1] != p.fend - p.fstart:
        problems.append("descriptor ram_end inconsistent with region length")
    return problems


def deflate(body: bytes, engine: str = "zlib") -> bytes:
    if engine == "zopfli":
        import zopfli.zopfli as z  # optional dependency: pip extra "zopfli"

        return z.compress(bytes(body), numiterations=5)[2:-4]  # zlib container without header and Adler-32
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 8)
    return c.compress(body) + c.flush()


def build(
    img: bytes, lay: Layout, body: bytes, prefix: bytes | None = None, stream: bytes | None = None, engine: str = "zlib"
) -> bytes:
    p = parse(img, lay)
    out = bytearray(img)
    if prefix is not None:
        if len(prefix) != lay.prefix_len:
            raise ContainerError("prefix length changed")
        out[p.fstart : p.sstart] = prefix
    stream = deflate(body, engine) if stream is None else stream
    if zlib.decompressobj(-15).decompress(stream) != body:
        raise ContainerError("DEFLATE round-trip failed")
    send = p.sstart + len(stream)
    fend = send + 6
    if fend > lay.tail_limit:
        raise ContainerError(f"AP region would end at {fend:#x}, past the fixed tail at {lay.tail_limit:#x}")
    out[p.sstart : lay.tail_limit] = bytes(lay.tail_limit - p.sstart)
    out[p.sstart : send] = stream
    struct.pack_into(
        "<IH", out, send, len(body), p.check
    )  # u16 check word kept: unknown algorithm, never verified at boot
    length = fend - p.fstart
    struct.pack_into("<I", out, p.fstart + lay.len_field, length)
    d = p.desc[:]
    d[2], d[3] = d[1] + length, fend
    d[5] = crc32_msb(bytes(out[p.fstart : fend]))
    struct.pack_into("<10I", out, lay.descriptor, *d)
    struct.pack_into(">I", out, p.fsz4, crc32_msb(bytes(out[: p.fsz4])))
    return bytes(out)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sector_diff(a: bytes, b: bytes, sector: int = 0x1000) -> list[int]:
    return [o for o in range(0, min(len(a), len(b)), sector) if a[o : o + sector] != b[o : o + sector]]
