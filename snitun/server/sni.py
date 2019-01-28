"""TLS ClientHello parser."""
import logging

from ..exceptions import ParseSNIError

_LOGGER = logging.getLogger(__name__)

TLS_HEADER_LEN = 5
TLS_HANDSHAKE_CONTENT_TYPE = 0x16
TLS_HANDSHAKE_TYPE_CLIENT_HELLO = 0x01


def parse_tls_sni(data: bytes) -> str:
    """Parse TLS SNI extention."""

    if len(data) < TLS_HEADER_LEN:
        _LOGGER.debug("Invalid TLS header")
        raise ParseSNIError()

    # If TLS handshake
    if data[0] != TLS_HANDSHAKE_CONTENT_TYPE:
        _LOGGER.debug("Not TLS handshake received")
        raise ParseSNIError()

    # Check compatible ClientHello
    if int(data[1]) < 3:
        _LOGGER.debug("Received ClientHello without SNI support")
        raise ParseSNIError()

    # Calculate TLS record size
    tls_size = (data[3] << 8) + data[4] + TLS_HEADER_LEN
    if len(data) < tls_size:
        _LOGGER.debug("Can't calculate the TLS record size")
        raise ParseSNIError()

    # Check if handshake is a ClientHello
    pos = TLS_HEADER_LEN
    if data[pos] != TLS_HANDSHAKE_TYPE_CLIENT_HELLO:
        _LOGGER.debug("Invalid ClientHello type")
        raise ParseSNIError()

    # Seek fixed length header part
    pos += 38

    # Seek SessionID
    try:
        pos += 1 + data[pos]
    except IndexError:
        _LOGGER.debug("Invalid SessionID")
        raise ParseSNIError() from None

    # Seek Cipher Suites
    try:
        pos += 2 + (data[pos] << 8) + data[pos + 1]
    except IndexError:
        _LOGGER.debug("Invalid CipherSuites")
        raise ParseSNIError() from None

    # Seek Compression Methods
    try:
        pos += 1 + data[pos]
    except IndexError:
        _LOGGER.debug("Invalid CompressionMethods")
        raise ParseSNIError() from None

    # Check data buffer + extension size
    if pos + 2 > len(data):
        _LOGGER.debug("Mismatch Extension TLS header")
        raise ParseSNIError()

    # Process extension
    return _parse_extension(data, pos)


def _parse_extension(data: bytes, pos: int) -> str:
    """Parse TLS ClientHello Extension."""

    # Seek Extension start
    try:
        tls_extension_size = (data[pos] << 8) + data[pos + 1]
        pos += 2
    except IndexError:
        raise ParseSNIError() from None

    # Check data buffer + extension size
    if pos + tls_extension_size > len(data):
        _LOGGER.debug("Mismatch Extension TLS header")
        raise ParseSNIError()

    # Loop over extension until we have our SNI
    while pos + 4 <= len(data):

        # SNI?
        if data[pos] == 0x00 and data[pos + 1] == 0x00:
            return _parse_host_name(data, pos + 4)

        pos += 4 + (data[pos + 2] << 8) + data[pos + 3]

    _LOGGER.debug("Can't find any ServerName Extension")
    raise ParseSNIError()


def _parse_host_name(data: bytes, pos: int) -> str:
    """Parse TLS ServerName Extension."""

    # Seek list size
    pos += 2

    while pos + 3 < len(data):
        size = (data[pos + 1] << 8) + data[pos + 2]

        # Unknown server name type
        if data[pos] != 0x00:
            _LOGGER.debug("Unknown ServerName type")
            pos += 3 + size
            continue

        try:
            return bytes(data[pos + 3:pos + 3 + size]).decode()
        except IndexError:
            _LOGGER.debug("Wrong host length")
            raise ParseSNIError() from None

    _LOGGER.debug("Not found any valid ServerName")
    raise ParseSNIError()
