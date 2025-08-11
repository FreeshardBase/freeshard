import importlib

import pytest

from shard_core.service import human_encoding as he


@pytest.fixture(autouse=True)
def reload_human_encoding_module():
    # we call the he.init() method during the tests. This is to restore the original initialization after each test.
    yield
    importlib.reload(he)


def test_coding_without_init():
    original = b"foobar"
    encoded = he.encode(original)
    decoded = he.decode(encoded)
    assert original == decoded


def test_init():
    he.init("0123")
    assert he.bits_per_char == 2


def test_init_non_unique():
    with pytest.raises(he.InitializationError):
        he.init("00")


def test_coding_normal():
    he.init("0123")
    original = b"foobar"
    encoded = he.encode(original)
    decoded = he.decode(encoded)
    assert original == decoded
    assert len(encoded) == 6 * 4  # text length * chars per byte


def test_init_uneven():
    he.init("01234")
    assert he.bits_per_char == 2


def test_coding_unaligned():
    he.init("01234567")
    assert he.bits_per_char == 3
    original = b"f"  # 8 bits
    encoded = he.encode(original)
    decoded = he.decode(encoded)
    assert original == decoded


def test_decode_invalid_overhang():
    he.init("01234567")
    with pytest.raises(he.DecodingError):
        he.decode("315")


def test_random_string():
    choices = "01234567"
    he.init(choices)
    r = he.random_string(8)
    assert len(r) == 8
    assert all(digit in choices for digit in r)
