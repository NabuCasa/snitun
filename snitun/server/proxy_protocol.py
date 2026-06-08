"""PROXY protocol header parser (v1 text and v2 binary).

The PROXY protocol (defined by HAProxy) prepends a small header to a forwarded
connection so the backend learns the original client address. SniTun only needs
the *source* address of that header - it is the IP that gets forwarded to the
peer - so the parser deliberately extracts nothing else and walks the minimum
number of bytes required to find it and to know how long the header is.

Spec: https://www.haproxy.org/download/2.8/doc/proxy-protocol.txt

SECURITY: a PROXY header is fully attacker-controlled (a client can simply send
one), so the result of this parser must only be trusted when SniTun is
configured to sit behind a known proxy. Callers gate parsing behind an explicit,
off-by-default flag.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress

from ..exceptions import (
    ParseProxyProtocolError,
    ParseProxyProtocolIncompleteError,
)

# Upper bound on how much we will buffer while waiting for a complete header.
# A v1 header is at most 108 bytes; a v2 header is 16 bytes plus an address
# block that in practice is tiny. This bounds the work an upstream proxy (the
# only source we trust to send a header) can make us do.
_MAX_HEADER_SIZE = 1500

# v1 is a single CRLF-terminated ASCII line; the spec caps it at 107 bytes of
# content plus the CRLF.
_V1_PREFIX = b"PROXY "
_V1_MAX_LEN = 108
_V1_CRLF = b"\r\n"

# v2 starts with a fixed 12 byte signature followed by a 4 byte header.
_V2_SIGNATURE = b"\r\n\r\n\x00\r\nQUIT\n"
_V2_HEADER_LEN = 16
_V2_VERSION = 0x20  # high nibble of byte 12

# v2 commands (low nibble of byte 12)
_V2_CMD_LOCAL = 0x00
_V2_CMD_PROXY = 0x01

# v2 address families (high nibble of byte 13)
_V2_FAMILY_INET = 0x10
_V2_FAMILY_INET6 = 0x20

# Length of the address block that carries the source address for each family.
_V2_INET_ADDR_LEN = 12  # 4 + 4 + 2 + 2
_V2_INET6_ADDR_LEN = 36  # 16 + 16 + 2 + 2


@dataclass(slots=True, frozen=True)
class ProxyProtocolHeader:
    """A parsed PROXY protocol header.

    ``source`` is the original client address, or ``None`` when the header
    carries no usable address (v1 ``UNKNOWN``, v2 ``LOCAL`` or an unsupported
    address family). ``size`` is the number of leading bytes the header
    occupies and that must be stripped before the real payload begins.
    """

    source: ipaddress.IPv4Address | ipaddress.IPv6Address | None
    size: int


def parse_proxy_protocol_header(data: bytes) -> ProxyProtocolHeader | None:
    """Parse a PROXY protocol header from the start of ``data``.

    Returns ``None`` if ``data`` does not start with a PROXY protocol header.
    Raises :class:`ParseProxyProtocolIncompleteError` if a header has started
    but ``data`` does not yet contain all of it, and
    :class:`ParseProxyProtocolError` if the header is malformed.
    """
    if data.startswith(_V2_SIGNATURE):
        return _parse_v2(data)
    if data.startswith(_V1_PREFIX):
        return _parse_v1(data)
    # A header may not have fully arrived yet; only treat a partial match of a
    # known signature as "incomplete", everything else is "not PROXY".
    if _V2_SIGNATURE.startswith(data) or _V1_PREFIX.startswith(data):
        raise ParseProxyProtocolIncompleteError
    return None


def _parse_v1(data: bytes) -> ProxyProtocolHeader:
    r"""Parse a v1 (text) PROXY header: ``PROXY <proto> <src> <dst> ...\r\n``."""
    end = data.find(_V1_CRLF)
    if end == -1:
        if len(data) >= _V1_MAX_LEN:
            raise ParseProxyProtocolError("PROXY v1 header without CRLF")
        raise ParseProxyProtocolIncompleteError
    if end + len(_V1_CRLF) > _V1_MAX_LEN:
        raise ParseProxyProtocolError("PROXY v1 header exceeds maximum length")

    size = end + len(_V1_CRLF)
    fields = data[:end].split(b" ")
    protocol = fields[1] if len(fields) > 1 else b""

    # No address information is provided.
    if protocol == b"UNKNOWN":
        return ProxyProtocolHeader(None, size)

    if protocol not in (b"TCP4", b"TCP6"):
        raise ParseProxyProtocolError(f"Unsupported PROXY v1 protocol: {protocol!r}")

    # PROXY <proto> <src ip> <dst ip> <src port> <dst port>
    if len(fields) != 6:
        raise ParseProxyProtocolError("Malformed PROXY v1 header")

    try:
        source = ipaddress.ip_address(fields[2].decode("ascii"))
    except (ValueError, UnicodeDecodeError) as err:
        raise ParseProxyProtocolError("Invalid PROXY v1 source address") from err

    # The address family must match the declared protocol.
    if (protocol == b"TCP4") != isinstance(source, ipaddress.IPv4Address):
        raise ParseProxyProtocolError("PROXY v1 address family mismatch")

    return ProxyProtocolHeader(source, size)


def _parse_v2(data: bytes) -> ProxyProtocolHeader:
    """Parse a v2 (binary) PROXY header."""
    if len(data) < _V2_HEADER_LEN:
        raise ParseProxyProtocolIncompleteError

    version_command = data[12]
    if version_command & 0xF0 != _V2_VERSION:
        raise ParseProxyProtocolError("Unsupported PROXY protocol version")

    family_protocol = data[13]
    address_len = (data[14] << 8) | data[15]
    size = _V2_HEADER_LEN + address_len
    if len(data) < size:
        raise ParseProxyProtocolIncompleteError

    command = version_command & 0x0F
    # LOCAL connections (health checks) carry no real client address.
    if command == _V2_CMD_LOCAL:
        return ProxyProtocolHeader(None, size)
    if command != _V2_CMD_PROXY:
        raise ParseProxyProtocolError("Unsupported PROXY v2 command")

    family = family_protocol & 0xF0
    block = data[_V2_HEADER_LEN:size]
    if family == _V2_FAMILY_INET:
        if address_len < _V2_INET_ADDR_LEN:
            raise ParseProxyProtocolError("Truncated PROXY v2 IPv4 address block")
        return ProxyProtocolHeader(ipaddress.IPv4Address(block[0:4]), size)
    if family == _V2_FAMILY_INET6:
        if address_len < _V2_INET6_ADDR_LEN:
            raise ParseProxyProtocolError("Truncated PROXY v2 IPv6 address block")
        return ProxyProtocolHeader(ipaddress.IPv6Address(block[0:16]), size)

    # AF_UNSPEC or AF_UNIX - the connection is proxied but has no IP address we
    # can forward; strip the header and fall back to the socket peer.
    return ProxyProtocolHeader(None, size)


async def read_proxy_protocol_header(
    reader: asyncio.StreamReader,
) -> tuple[ProxyProtocolHeader | None, bytes]:
    """Read and strip a PROXY protocol header from ``reader``.

    Returns ``(header, leftover)`` where ``leftover`` is the payload that has
    already been read from the stream and follows the header. ``header`` is
    ``None`` when the stream does not start with a PROXY header, in which case
    ``leftover`` is whatever was read and must still be processed.

    Raises :class:`ParseProxyProtocolError` for a malformed header or if the
    connection closes before the header is complete.
    """
    buffer = b""
    while True:
        try:
            header = parse_proxy_protocol_header(buffer)
        except ParseProxyProtocolIncompleteError:
            if len(buffer) >= _MAX_HEADER_SIZE:
                raise ParseProxyProtocolError(
                    "PROXY protocol header exceeds maximum size",
                ) from None
            chunk = await reader.read(_MAX_HEADER_SIZE - len(buffer))
            if not chunk:
                raise ParseProxyProtocolError(
                    "Connection closed during PROXY protocol header",
                ) from None
            buffer += chunk
            continue

        if header is None:
            return None, buffer
        return header, buffer[header.size :]
