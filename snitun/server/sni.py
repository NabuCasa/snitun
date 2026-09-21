"""TLS ClientHello parser."""

from __future__ import annotations

import asyncio
import logging

from ..exceptions import ParseSNIError, ParseSNIIncompleteError
from ..utils.server import MAX_BUFFER_SIZE, MAX_READ_SIZE

_LOGGER = logging.getLogger(__name__)

TLS_HEADER_LEN = 5
TLS_HANDSHAKE_HEADER_LEN = 4
TLS_HANDSHAKE_CONTENT_TYPE = 0x16
TLS_HANDSHAKE_TYPE_CLIENT_HELLO = 0x01


async def payload_reader(
    reader: asyncio.StreamReader,
    initial: bytes = b"",
) -> bytes | None:
    """Read data from reader.

    ``initial`` carries any bytes already read from the stream (for example
    the payload that followed a stripped PROXY protocol header) so they are
    not lost.
    """
    data = initial
    # We need at least 6 bytes: the 5-byte TLS record header plus the
    # handshake type byte (read below as data[5]). read() returns whatever is
    # available, so loop until we have enough or the peer stops sending. A
    # short read or EOF means there is no usable ClientHello -> bail (None).
    # A reset/broken connection raises OSError here, which the caller handles.
    while len(data) < 6:
        chunk = await reader.read(MAX_READ_SIZE)
        if not chunk:
            return None
        data += chunk

    if (
        data[0] != TLS_HANDSHAKE_CONTENT_TYPE
        or data[5] != TLS_HANDSHAKE_TYPE_CLIENT_HELLO
    ):
        return None

    tls_size = (data[3] << 8) + data[4] + TLS_HEADER_LEN
    while (data_size := len(data)) < tls_size and data_size <= MAX_BUFFER_SIZE:
        chunk = await reader.read(MAX_READ_SIZE)
        if not chunk:
            # EOF before the full record arrived; avoid spinning on read().
            return None
        data += chunk

    return data


def parse_tls_sni(data: bytes) -> str:
    """Parse TLS SNI extension."""
    if (data_size := len(data)) < TLS_HEADER_LEN:
        _LOGGER.debug("Invalid TLS header")
        raise ParseSNIError

    # If TLS handshake
    if data[0] != TLS_HANDSHAKE_CONTENT_TYPE:
        _LOGGER.debug("Not TLS handshake received")
        raise ParseSNIError

    # Check compatible ClientHello
    if int(data[1]) < 3:
        _LOGGER.debug("Received ClientHello without SNI support")
        raise ParseSNIError

    # Calculate TLS record size
    tls_size = (data[3] << 8) + data[4] + TLS_HEADER_LEN
    if data_size < tls_size:
        _LOGGER.debug("Can't calculate the TLS record size")
        raise ParseSNIIncompleteError

    if tls_size < TLS_HEADER_LEN + TLS_HANDSHAKE_HEADER_LEN:
        _LOGGER.debug("Invalid handshake header length")
        raise ParseSNIError

    # Check if handshake is a ClientHello
    pos = TLS_HEADER_LEN
    if data[pos] != TLS_HANDSHAKE_TYPE_CLIENT_HELLO:
        _LOGGER.debug("Invalid ClientHello type")
        raise ParseSNIError

    # Bound parsing to this ClientHello, not subsequent bytes in the TCP read.
    hello_size = (
        TLS_HEADER_LEN
        + TLS_HANDSHAKE_HEADER_LEN
        + int.from_bytes(data[pos + 1 : pos + TLS_HANDSHAKE_HEADER_LEN], "big")
    )
    if hello_size > tls_size:
        _LOGGER.debug("ClientHello exceeds TLS record")
        raise ParseSNIError

    # Seek fixed length header part
    pos += 38

    # Seek SessionID
    if pos >= hello_size:
        _LOGGER.debug("Invalid SessionID")
        raise ParseSNIError
    pos += 1 + data[pos]

    # Seek Cipher Suites
    if pos + 2 > hello_size:
        _LOGGER.debug("Invalid CipherSuites")
        raise ParseSNIError
    pos += 2 + (data[pos] << 8) + data[pos + 1]

    # Seek Compression Methods
    if pos >= hello_size:
        _LOGGER.debug("Invalid CompressionMethods")
        raise ParseSNIError
    pos += 1 + data[pos]

    # Check data buffer + extension size
    if pos + 2 > hello_size:
        _LOGGER.debug("Mismatch Extension TLS header")
        raise ParseSNIError

    # Process extension
    return _parse_extension(data, pos, hello_size)


def _parse_extension(data: bytes, pos: int, data_size: int) -> str:
    """Parse TLS ClientHello Extension."""
    # Seek Extension start
    tls_extension_size = (data[pos] << 8) + data[pos + 1]
    pos += 2

    # Check data buffer + extension size
    if pos + tls_extension_size != data_size:
        _LOGGER.debug("Mismatch Extension TLS header")
        raise ParseSNIError

    # Loop over extension until we have our SNI
    while pos + 4 <= data_size:
        extension_end = pos + 4 + (data[pos + 2] << 8) + data[pos + 3]
        if extension_end > data_size:
            _LOGGER.debug("Extension exceeds ClientHello")
            raise ParseSNIError

        # SNI?
        if data[pos] == 0x00 and data[pos + 1] == 0x00:
            return _parse_host_name(data, pos + 4, extension_end)

        pos = extension_end

    _LOGGER.debug("Can't find any ServerName Extension")
    raise ParseSNIError


def _parse_host_name(data: bytes, pos: int, data_size: int) -> str:
    """Parse TLS ServerName Extension."""
    if pos + 2 > data_size:
        _LOGGER.debug("Missing ServerName list length")
        raise ParseSNIError
    list_size = (data[pos] << 8) + data[pos + 1]
    pos += 2
    if not list_size or pos + list_size != data_size:
        _LOGGER.debug("Mismatch ServerName list length")
        raise ParseSNIError

    while pos + 3 <= data_size:
        size = (data[pos + 1] << 8) + data[pos + 2]
        name_end = pos + 3 + size
        if name_end > data_size:
            _LOGGER.debug("ServerName exceeds list")
            raise ParseSNIError

        # Unknown server name type
        if data[pos] != 0x00:
            _LOGGER.debug("Unknown ServerName type")
            pos = name_end
            continue

        if not size:
            _LOGGER.debug("Empty host name")
            raise ParseSNIError
        try:
            return data[pos + 3 : name_end].decode("utf-8")
        except UnicodeDecodeError:
            _LOGGER.debug("Wrong host length/format")
            raise ParseSNIError from None

    _LOGGER.debug("Not found any valid ServerName")
    raise ParseSNIError
