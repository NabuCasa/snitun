"""Test ipaddress module."""
from ipaddress import ip_address

from snitun.utils import ipaddress as ip_modul


def test_ipaddress_to_binary():
    """Test ip address to binary."""
    my_ip = ip_address("192.168.1.1")
    my_ip_bin = b"\xc0\xa8\x01\x01"

    assert ip_modul.ip_address_to_bytes(my_ip) == my_ip_bin


def test_binary_to_ipaddress():
    """Test ip address to binary."""
    my_ip = ip_address("192.168.1.1")
    my_ip_bin = b"\xc0\xa8\x01\x01"

    assert ip_modul.bytes_to_ip_address(my_ip_bin) == my_ip
