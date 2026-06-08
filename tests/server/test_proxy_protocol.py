"""Tests for the PROXY protocol parser."""

from __future__ import annotations

import asyncio
import ipaddress
import struct

import pytest

from snitun.exceptions import (
    ParseProxyProtocolError,
    ParseProxyProtocolIncompleteError,
)
from snitun.server.proxy_protocol import (
    ProxyProtocolHeader,
    parse_proxy_protocol_header,
    read_proxy_protocol_header,
)

V2_SIGNATURE = b"\r\n\r\n\x00\r\nQUIT\n"


def _v2_header(
    command: int,
    family_protocol: int,
    address_block: bytes,
) -> bytes:
    """Build a v2 PROXY header."""
    return (
        V2_SIGNATURE
        + bytes([command, family_protocol])
        + struct.pack("!H", len(address_block))
        + address_block
    )


def _v2_inet_block(
    src: str,
    dst: str = "10.0.0.1",
    src_port: int = 1234,
    dst_port: int = 443,
    extra: bytes = b"",
) -> bytes:
    """Build a v2 IPv4 address block (optionally with trailing TLVs)."""
    return (
        ipaddress.IPv4Address(src).packed
        + ipaddress.IPv4Address(dst).packed
        + struct.pack("!HH", src_port, dst_port)
        + extra
    )


def _v2_inet6_block(src: str, dst: str = "::1") -> bytes:
    """Build a v2 IPv6 address block."""
    return (
        ipaddress.IPv6Address(src).packed
        + ipaddress.IPv6Address(dst).packed
        + struct.pack("!HH", 1234, 443)
    )


# --- no header -------------------------------------------------------------


def test_not_proxy_protocol() -> None:
    """TLS / other traffic is reported as not being a PROXY header."""
    assert parse_proxy_protocol_header(b"\x16\x03\x01\x00\x00") is None
    assert parse_proxy_protocol_header(b"gAxxxx") is None
    assert parse_proxy_protocol_header(b"GET / HTTP/1.1\r\n") is None


# --- v1 --------------------------------------------------------------------


def test_v1_tcp4() -> None:
    """A v1 TCP4 header yields the source address and is stripped."""
    raw = b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443\r\n" + b"\x16payload"
    header = parse_proxy_protocol_header(raw)
    assert header == ProxyProtocolHeader(ipaddress.IPv4Address("1.2.3.4"), 37)
    assert raw[header.size :] == b"\x16payload"


def test_v1_tcp6() -> None:
    """A v1 TCP6 header yields an IPv6 source address."""
    raw = b"PROXY TCP6 2001:db8::1 2001:db8::2 1111 443\r\nrest"
    header = parse_proxy_protocol_header(raw)
    assert header.source == ipaddress.IPv6Address("2001:db8::1")
    assert raw[header.size :] == b"rest"


def test_v1_unknown_has_no_source() -> None:
    """A v1 UNKNOWN header is stripped but carries no source address."""
    header = parse_proxy_protocol_header(b"PROXY UNKNOWN\r\npayload")
    assert header == ProxyProtocolHeader(None, 15)


@pytest.mark.parametrize(
    "raw",
    [
        b"PROXY TCP4 1.2.3.4 5.6.7.8 1111\r\n",  # too few fields
        b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 443 extra\r\n",  # too many fields
        b"PROXY TCP9 1.2.3.4 5.6.7.8 1111 443\r\n",  # unknown protocol
        b"PROXY TCP4 999.1.1.1 5.6.7.8 1111 443\r\n",  # invalid source ip
        b"PROXY TCP4 2001:db8::1 5.6.7.8 1 2\r\n",  # family mismatch (v6 in TCP4)
        b"PROXY TCP6 1.2.3.4 5.6.7.8 1 2\r\n",  # family mismatch (v4 in TCP6)
    ],
)
def test_v1_malformed(raw: bytes) -> None:
    """Malformed v1 headers are rejected."""
    with pytest.raises(ParseProxyProtocolError):
        parse_proxy_protocol_header(raw)


def test_v1_no_crlf_within_limit_is_incomplete() -> None:
    """A v1 header without a CRLF yet (under the size cap) needs more data."""
    with pytest.raises(ParseProxyProtocolIncompleteError):
        parse_proxy_protocol_header(b"PROXY TCP4 1.2.3.4 5.6.7.8 1111 44")


def test_v1_no_crlf_over_limit_is_error() -> None:
    """A v1 header that exceeds the maximum length without a CRLF is rejected."""
    with pytest.raises(ParseProxyProtocolError):
        parse_proxy_protocol_header(b"PROXY " + b"9" * 200)


# --- v2 --------------------------------------------------------------------


def test_v2_inet() -> None:
    """A v2 IPv4 PROXY header yields the source address and is stripped."""
    raw = _v2_header(0x21, 0x11, _v2_inet_block("9.9.9.9")) + b"\x16tls"
    header = parse_proxy_protocol_header(raw)
    assert header.source == ipaddress.IPv4Address("9.9.9.9")
    assert raw[header.size :] == b"\x16tls"


def test_v2_inet6() -> None:
    """A v2 IPv6 PROXY header yields the source address."""
    raw = _v2_header(0x21, 0x21, _v2_inet6_block("2001:db8::dead"))
    header = parse_proxy_protocol_header(raw)
    assert header.source == ipaddress.IPv6Address("2001:db8::dead")


def test_v2_inet_with_tlv_trailer() -> None:
    """Trailing TLV vectors are counted in size but ignored for the source."""
    block = _v2_inet_block("9.9.9.9", extra=b"\x03\x00\x04abcd")
    raw = _v2_header(0x21, 0x11, block) + b"after"
    header = parse_proxy_protocol_header(raw)
    assert header.source == ipaddress.IPv4Address("9.9.9.9")
    assert raw[header.size :] == b"after"


def test_v2_local_has_no_source() -> None:
    """A v2 LOCAL header (health check) carries no source address."""
    header = parse_proxy_protocol_header(_v2_header(0x20, 0x00, b"") + b"x")
    assert header == ProxyProtocolHeader(None, 16)


def test_v2_unspec_family_has_no_source() -> None:
    """An unsupported address family is stripped but yields no source."""
    header = parse_proxy_protocol_header(_v2_header(0x21, 0x00, b"\x00\x00\x00\x00"))
    assert header.source is None


@pytest.mark.parametrize(
    "raw",
    [
        _v2_header(0x11, 0x11, _v2_inet_block("9.9.9.9")),  # wrong version
        _v2_header(0x2F, 0x11, _v2_inet_block("9.9.9.9")),  # unknown command
        _v2_header(0x21, 0x11, b"\x01\x02\x03"),  # truncated v4 block
        _v2_header(0x21, 0x21, b"\x01\x02\x03"),  # truncated v6 block
    ],
)
def test_v2_malformed(raw: bytes) -> None:
    """Malformed v2 headers are rejected."""
    with pytest.raises(ParseProxyProtocolError):
        parse_proxy_protocol_header(raw)


def test_v2_incomplete() -> None:
    """A v2 header that is not fully present yet needs more data."""
    full = _v2_header(0x21, 0x11, _v2_inet_block("9.9.9.9"))
    # Only the signature so far.
    with pytest.raises(ParseProxyProtocolIncompleteError):
        parse_proxy_protocol_header(V2_SIGNATURE)
    # Header announces a longer address block than is present.
    with pytest.raises(ParseProxyProtocolIncompleteError):
        parse_proxy_protocol_header(full[:-1])


def test_partial_signature_is_incomplete() -> None:
    """A leading fragment of a known signature is treated as incomplete."""
    with pytest.raises(ParseProxyProtocolIncompleteError):
        parse_proxy_protocol_header(b"PRO")
    with pytest.raises(ParseProxyProtocolIncompleteError):
        parse_proxy_protocol_header(V2_SIGNATURE[:5])
    with pytest.raises(ParseProxyProtocolIncompleteError):
        parse_proxy_protocol_header(b"")


def test_v1_crlf_present_but_over_limit() -> None:
    """A v1 line that terminates beyond the maximum length is rejected."""
    raw = b"PROXY TCP4 " + b"1" * 120 + b"\r\n"
    with pytest.raises(ParseProxyProtocolError):
        parse_proxy_protocol_header(raw)


# --- async reader ----------------------------------------------------------


async def test_read_header_v1() -> None:
    """The async reader returns the header and the payload that follows it."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"PROXY TCP4 1.2.3.4 5.6.7.8 1 2\r\nPAYLOAD")
    header, leftover = await read_proxy_protocol_header(reader)
    assert header is not None
    assert header.source == ipaddress.IPv4Address("1.2.3.4")
    assert leftover == b"PAYLOAD"


async def test_read_header_none_for_non_proxy() -> None:
    """The async reader returns None and the bytes read for non-PROXY data."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x16\x03\x01hello")
    header, leftover = await read_proxy_protocol_header(reader)
    assert header is None
    assert leftover == b"\x16\x03\x01hello"


async def test_read_header_split_across_reads() -> None:
    """The async reader keeps reading until the header is complete."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"PROXY TCP4 1.2.3.4")
    reader.feed_data(b" 5.6.7.8 1 2\r\nrest")
    header, leftover = await read_proxy_protocol_header(reader)
    assert header is not None
    assert header.source == ipaddress.IPv4Address("1.2.3.4")
    assert leftover == b"rest"


async def test_read_header_connection_closed() -> None:
    """A connection closing mid-header is an error."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"PROXY TCP4 1.2.3.4")
    reader.feed_eof()
    with pytest.raises(ParseProxyProtocolError):
        await read_proxy_protocol_header(reader)


async def test_read_header_exceeds_max_size() -> None:
    """A header that never completes is bounded and rejected."""
    reader = asyncio.StreamReader()
    # v2 header advertising a huge address block that never arrives.
    reader.feed_data(
        V2_SIGNATURE + bytes([0x21, 0x11]) + struct.pack("!H", 0xFFFF) + b"\x00" * 1600,
    )
    with pytest.raises(ParseProxyProtocolError):
        await read_proxy_protocol_header(reader)
