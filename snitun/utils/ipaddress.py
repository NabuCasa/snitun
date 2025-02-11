"""Utils for handling IP address."""

from functools import lru_cache
import ipaddress
import socket

EMPTY_IP_ADDRESS = ipaddress.IPv4Address(0)
EMPTY_IP_ADDRESS_BYTES = bytes(4)


@lru_cache
def bytes_to_ip_address(data: bytes) -> ipaddress.IPv4Address:
    """Convert bytes into a IP address."""
    try:
        return ipaddress.IPv4Address(socket.inet_ntop(socket.AF_INET, data))
    except (ValueError, OSError):
        return EMPTY_IP_ADDRESS


@lru_cache
def ip_address_to_bytes(ip_address: ipaddress.IPv4Address) -> bytes:
    """Convert a IP address object into bytes."""
    try:
        return socket.inet_pton(socket.AF_INET, str(ip_address))
    except OSError:
        return EMPTY_IP_ADDRESS_BYTES
