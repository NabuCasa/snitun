"""Utils for handling IP address."""

from collections.abc import Sequence
from functools import lru_cache
import ipaddress

EMPTY_IP_ADDRESS = ipaddress.IPv4Address(0)
EMPTY_IP_ADDRESS_BYTES = bytes(4)

# A bind host: a hostname/IP string or an ipaddress object, or a sequence of
# them (e.g. ``["0.0.0.0", IPv6Address("::")]`` to listen on IPv4 and IPv6).
type Host = str | ipaddress.IPv4Address | ipaddress.IPv6Address
type Hosts = Host | Sequence[Host] | None


def normalize_hosts(hosts: Hosts) -> list[str] | None:
    """Normalize a host argument into a list of address strings.

    Accepts a single host or a sequence, each as a string (hostname or IP) or
    an ipaddress object. Returns None when no host is given so the caller can
    pick its own default.
    """
    if hosts is None:
        return None
    if isinstance(hosts, str | ipaddress.IPv4Address | ipaddress.IPv6Address):
        return [str(hosts)]
    return [str(host) for host in hosts]


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
