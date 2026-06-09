"""Test the AccessList access policy."""

import ipaddress

from snitun.client.access_list import AccessList, AccessListAction

IP_ADDR = ipaddress.ip_address("8.8.8.8")
IP_ADDR_V6 = ipaddress.ip_address("2001:db8::1")
OTHER_ADDR = ipaddress.ip_address("8.8.1.1")


def test_default_is_empty_allow() -> None:
    """An access list defaults to an empty ALLOW list."""
    access_list = AccessList()
    assert access_list.default_action is AccessListAction.ALLOW
    assert access_list.ips == set()


def test_add_and_remove() -> None:
    """Add and remove IP addresses from the list."""
    access_list = AccessList()
    access_list.add(IP_ADDR)
    assert IP_ADDR in access_list.ips

    access_list.remove(IP_ADDR)
    assert IP_ADDR not in access_list.ips

    # Removing an absent IP is a no-op
    access_list.remove(IP_ADDR)


def test_allow_action() -> None:
    """ALLOW only permits the IPs in the list."""
    access_list = AccessList(default_action=AccessListAction.ALLOW)
    access_list.add(IP_ADDR)

    assert access_list.check_policy(IP_ADDR)
    assert not access_list.check_policy(OTHER_ADDR)


def test_allow_action_empty_blocks_everyone() -> None:
    """An empty ALLOW list blocks every IP."""
    access_list = AccessList(default_action=AccessListAction.ALLOW)
    assert not access_list.check_policy(IP_ADDR)


def test_block_action() -> None:
    """BLOCK blocks the IPs in the list and allows the rest."""
    access_list = AccessList(default_action=AccessListAction.BLOCK)
    access_list.add(IP_ADDR)

    assert not access_list.check_policy(IP_ADDR)
    assert access_list.check_policy(OTHER_ADDR)


def test_block_action_empty_allows_everyone() -> None:
    """An empty BLOCK list allows every IP."""
    access_list = AccessList(default_action=AccessListAction.BLOCK)
    assert access_list.check_policy(IP_ADDR)


def test_ipv6_addresses() -> None:
    """IPv6 addresses are handled like IPv4 ones."""
    access_list = AccessList(default_action=AccessListAction.ALLOW)
    access_list.add(IP_ADDR_V6)

    assert access_list.check_policy(IP_ADDR_V6)
    assert not access_list.check_policy(IP_ADDR)
