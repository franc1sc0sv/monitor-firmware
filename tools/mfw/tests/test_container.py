import pytest

from mfw import container
from mfw.crc import crc32_msb

from .conftest import LAY


def test_crc_check_value():
    assert crc32_msb(b"123456789") == 0x89A1897F


def test_synthetic_image_verifies(image):
    assert container.verify(image, LAY) == []


def test_unpack_returns_body(image, body):
    prefix, out = container.unpack(image, LAY)
    assert out == body and len(prefix) == LAY.prefix_len


def test_round_trip_with_original_stream_is_identical(image):
    p = container.parse(image, LAY)
    _, body = container.unpack(image, LAY)
    assert container.build(image, LAY, body, stream=image[p.sstart : p.send]) == image


def test_rebuild_with_changed_body_keeps_every_checksum_consistent(image, body):
    new_body = bytearray(body)
    new_body[100:104] = b"\xde\xad\xbe\xef"
    new = container.build(image, LAY, bytes(new_body))
    assert container.verify(new, LAY) == []
    assert container.unpack(new, LAY)[1] == bytes(new_body)
    assert container.parse(new, LAY).check == 0xBEEF  # unknown u16 check word is preserved


def test_corruption_is_detected(image):
    bad = bytearray(image)
    bad[0x2000 + LAY.prefix_len + 10] ^= 0xFF
    assert container.verify(bytes(bad), LAY)


def test_tail_overflow_is_refused(image):
    import os

    with pytest.raises(container.ContainerError, match="past the fixed tail"):
        container.build(image, LAY, os.urandom(0x8000))
