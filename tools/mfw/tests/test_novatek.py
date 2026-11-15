"""Novatek NVTSC_IMG package primitives. Uses only synthetic data; no vendor firmware bytes."""

import pytest

from mfw import novatek as nv

FAMILY = b"M-C5500GGZA"


def make_fake(version: str = "1002.1", filler: bytes = b"\x00" * 64) -> bytes:
    """A tiny stand-in image: magic, some filler, then the embedded id. Not real firmware."""
    return nv.MAGIC + filler + b"\x01\x02" + f"{FAMILY.decode()}-{version}".encode() + b"\xff" * 16


def test_sum16_and_tag():
    assert nv.sum16(b"\x00\x00") == 0
    assert nv.sum16(b"\xff\x01") == 0x100
    # sum wraps at 16 bits
    assert nv.sum16(b"\xff" * 0x101) == (0xFF * 0x101) & 0xFFFF
    assert nv.tag(b"\x45\xc1" + b"\x00" * 6) == "0106"


def test_parse_filename_roundtrip():
    n = nv.parse_filename("M-C5500GGZA-1008.3[C145].img")
    assert (n.family, n.version, n.tag) == ("M-C5500GGZA", "1008.3", "C145")
    assert n.filename == "M-C5500GGZA-1008.3[C145].img"


def test_parse_filename_lowercase_tag_normalised():
    assert nv.parse_filename("M-C5500GGZA-1008.3[c145].img").tag == "C145"


@pytest.mark.parametrize("bad", ["x.img", "M-C5500GGZA-1008.3.img", "M-C5500GGZA-108.3[C145].img", "foo[C145].img"])
def test_parse_filename_rejects_bad(bad):
    with pytest.raises(nv.NovatekError):
        nv.parse_filename(bad)


def test_find_embedded_id():
    img = make_fake("1002.1")
    emb = nv.find_embedded_id(img, FAMILY)
    assert emb.family == "M-C5500GGZA"
    assert emb.version == "1002.1"
    assert img[emb.offset : emb.offset + len(emb.text)] == b"M-C5500GGZA-1002.1"


def test_identify_has_magic():
    info = nv.identify(make_fake(), FAMILY)
    assert info.magic is True
    assert info.embedded.version == "1002.1"


def test_verify_stock_consistent():
    img = make_fake("1002.1")
    name = f"M-C5500GGZA-1002.1[{nv.tag(img)}].img"
    info = nv.verify_stock(img, name, family=FAMILY)
    assert info.embedded.version == "1002.1"


def test_verify_stock_detects_tag_mismatch():
    img = make_fake("1002.1")
    with pytest.raises(nv.NovatekError, match="sum16"):
        nv.verify_stock(img, "M-C5500GGZA-1002.1[0000].img", family=FAMILY)


def test_verify_stock_detects_version_mismatch():
    img = make_fake("1002.1")
    name = f"M-C5500GGZA-1008.3[{nv.tag(img)}].img"
    with pytest.raises(nv.NovatekError, match="version"):
        nv.verify_stock(img, name, family=FAMILY)


def test_restamp_keeps_length_and_recomputes_tag():
    img = make_fake("1002.1")
    out, name = nv.restamp(img, "1009.0", family=FAMILY)
    assert len(out) == len(img)
    assert nv.find_embedded_id(out, FAMILY).version == "1009.0"
    assert name.version == "1009.0"
    # the returned name's tag is the real sum16 of the restamped bytes -> self-consistent
    assert name.tag == nv.tag(out)
    assert nv.verify_stock(out, name.filename, family=FAMILY).embedded.version == "1009.0"


def test_restamp_rejects_bad_version():
    with pytest.raises(nv.NovatekError):
        nv.restamp(make_fake(), "10090", family=FAMILY)
