"""Utils for handling IP address."""

from functools import lru_cache
import ipaddress

EMPTY_IP_ADDRESS = ipaddress.IPv4Address(0)
EMPTY_IP_ADDRESS_BYTES = bytes(4)


@lru_cache
def bytes_to_ip_address(
    data: bytes,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Convert packed bytes into an IP address.

    4 bytes is decoded as IPv4, 16 bytes as IPv6.
    """
    try:
        return ipaddress.ip_address(data)
    except ValueError:
        return EMPTY_IP_ADDRESS


@lru_cache
def ip_address_to_bytes(
    ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bytes:
    """Convert an IP address object into packed bytes (4 for v4, 16 for v6)."""
    return ip_address.packed
