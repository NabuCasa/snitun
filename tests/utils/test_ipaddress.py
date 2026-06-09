"""Test ipaddress module."""

from ipaddress import ip_address

from snitun.utils import ipaddress as ip_modul
from snitun.utils.ipaddress import normalize_hosts


def test_ipaddress_to_binary() -> None:
    """Test ip address to binary."""
    my_ip = ip_address("192.168.1.1")
    my_ip_bin = b"\xc0\xa8\x01\x01"

    assert ip_modul.ip_address_to_bytes(my_ip) == my_ip_bin


def test_binary_to_ipaddress() -> None:
    """Test ip address to binary."""
    my_ip = ip_address("192.168.1.1")
    my_ip_bin = b"\xc0\xa8\x01\x01"

    assert ip_modul.bytes_to_ip_address(my_ip_bin) == my_ip


def test_ipv6_roundtrip() -> None:
    """An IPv6 address packs to 16 bytes and round-trips."""
    my_ip = ip_address("2001:db8::dead:beef")

    packed = ip_modul.ip_address_to_bytes(my_ip)
    assert len(packed) == 16
    assert ip_modul.bytes_to_ip_address(packed) == my_ip


def test_invalid_bytes_returns_empty() -> None:
    """Bytes that are neither 4 nor 16 long decode to the empty address."""
    assert ip_modul.bytes_to_ip_address(b"\x00\x00\x00") == ip_modul.EMPTY_IP_ADDRESS


def test_normalize_hosts_none() -> None:
    """None yields None so the caller can pick its own default."""
    assert normalize_hosts(None) is None


def test_normalize_hosts_single() -> None:
    """A single string or ipaddress object yields a one-element list."""
    assert normalize_hosts("0.0.0.0") == ["0.0.0.0"]
    assert normalize_hosts(ip_address("127.0.0.1")) == ["127.0.0.1"]
    assert normalize_hosts(ip_address("::1")) == ["::1"]


def test_normalize_hosts_sequence_mixed() -> None:
    """A sequence of mixed strings and ipaddress objects is stringified."""
    assert normalize_hosts(["0.0.0.0", ip_address("::1")]) == ["0.0.0.0", "::1"]
