"""Builds a synthetic MST9U container so the builder can be tested without vendor firmware."""

import struct
import zlib

import pytest

from mfw.container import Layout
from mfw.crc import crc32_msb

LAY = Layout(descriptor=0x1000, prefix_len=0x100, len_field=0x40, tail_limit=0x6000)
SIZE = 0x8000


def make_image(body: bytes, check: int = 0xBEEF) -> bytes:
    img = bytearray(b"\xff" * SIZE)
    fstart = 0x2000
    prefix = bytearray(b"P" * LAY.prefix_len)
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 8)
    stream = c.compress(body) + c.flush()
    sstart = fstart + LAY.prefix_len
    send = sstart + len(stream)
    fend = send + 6
    img[sstart : LAY.tail_limit] = bytes(LAY.tail_limit - sstart)
    struct.pack_into("<I", prefix, LAY.len_field, fend - fstart)
    img[fstart:sstart] = prefix
    img[sstart:send] = stream
    struct.pack_into("<IH", img, send, len(body), check)
    fsz4 = 0x7000
    desc = [
        fstart,
        0x200000,
        0x200000 + (fend - fstart),
        fend,
        0,
        crc32_msb(bytes(img[fstart:fend])),
        0,
        0,
        fsz4,
        LAY.descriptor,
    ]
    struct.pack_into("<10I", img, LAY.descriptor, *desc)
    struct.pack_into(">I", img, fsz4, crc32_msb(bytes(img[:fsz4])))
    return bytes(img)


@pytest.fixture
def body() -> bytes:
    return bytes(range(256)) * 32


@pytest.fixture
def image(body) -> bytes:
    return make_image(body)
