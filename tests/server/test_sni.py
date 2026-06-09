"""Tests for SNI parser."""

import asyncio

import pytest

from snitun.exceptions import ParseSNIError
from snitun.server import sni

from . import const_tls as raw


@pytest.mark.parametrize(
    "test_package",
    [
        raw.TLS_1_0,
        raw.TLS_1_0_OLD,
        raw.TLS_1_2,
        raw.TLS_1_2_MORE,
        raw.TLS_1_2_ORDER,
        raw.TLS_1_2_BAD,
    ],
)
def test_good_client_hello(test_package: bytes) -> None:
    """Test good TLS packages."""
    assert sni.parse_tls_sni(test_package) == "localhost"


@pytest.mark.parametrize(
    "test_package",
    [raw.BAD_DATA1, raw.BAD_DATA2, raw.SSL_2_0, raw.SSL_3_0],
)
def test_bad_client_hello(test_package: bytes) -> None:
    """Test bad client hello."""
    with pytest.raises(ParseSNIError):
        sni.parse_tls_sni(test_package)


class _ChunkReader:
    """Minimal async reader that yields pre-set chunks, then EOF."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)

    async def read(self, _n: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


async def test_payload_reader_good() -> None:
    """A complete ClientHello is returned intact."""
    reader = asyncio.StreamReader()
    reader.feed_data(raw.TLS_1_2)
    reader.feed_eof()

    assert await sni.payload_reader(reader) == raw.TLS_1_2


async def test_payload_reader_completes_across_reads() -> None:
    """A record split across multiple reads is reassembled."""
    reader = _ChunkReader(raw.TLS_1_2[:6], raw.TLS_1_2[6:])

    assert await sni.payload_reader(reader) == raw.TLS_1_2  # type: ignore[arg-type]


async def test_payload_reader_short_record_header() -> None:
    """A stream shorter than the 6-byte record header returns None (no OOB)."""
    reader = asyncio.StreamReader()
    # Exactly 5 bytes starting with the handshake content type: the old code
    # indexed data[5] here and raised IndexError.
    reader.feed_data(b"\x16\x03\x01\x00\x05")
    reader.feed_eof()

    assert await sni.payload_reader(reader) is None


async def test_payload_reader_eof_mid_record() -> None:
    """EOF before the full TLS record arrives returns None (no busy-spin)."""
    reader = asyncio.StreamReader()
    # Valid 6-byte prefix declaring a large record, then EOF.
    reader.feed_data(b"\x16\x03\x01\xff\xff\x01")
    reader.feed_eof()

    assert await sni.payload_reader(reader) is None


async def test_payload_reader_not_handshake() -> None:
    """Non-handshake content type returns None."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x17\x03\x01\x00\x01\x01")
    reader.feed_eof()

    assert await sni.payload_reader(reader) is None
