"""Access control list for connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    ip_network,
)

type IPAddress = IPv4Address | IPv6Address
type IPNetwork = IPv4Network | IPv6Network
type IPNetworkLike = str | IPAddress | IPNetwork


class AccessListAction(StrEnum):
    """Action of an :class:`AccessList`.

    The action defines how the networks in the list are treated:

    * ``ALLOW`` (old behavior): only the IPs in the list may connect, every
      other IP is blocked.
    * ``BLOCK``: the IPs in the list are blocked, every other IP may connect.
    """

    ALLOW = "allow"
    BLOCK = "block"


@dataclass(slots=True)
class AccessList:
    """Per-IP access policy for a connector.

    ``default_action`` selects the policy applied to the networks in
    ``networks`` (see :class:`AccessListAction`). With the default ``ALLOW``
    action an empty list blocks everyone; with ``BLOCK`` an empty list allows
    everyone.

    Each entry is an IP network. A single host is stored as a ``/32`` (IPv4) or
    ``/128`` (IPv6) network, so addresses, network objects, and CIDR strings
    (e.g. ``"10.0.0.0/8"``) can all be added.
    """

    default_action: AccessListAction = AccessListAction.ALLOW
    networks: set[IPNetwork] = field(default_factory=set)

    def add(self, network: IPNetworkLike) -> None:
        """Add an IP address or network (CIDR) to the list."""
        self.networks.add(ip_network(network, strict=False))

    def remove(self, network: IPNetworkLike) -> None:
        """Remove an IP address or network from the list (no error if absent)."""
        self.networks.discard(ip_network(network, strict=False))

    def check_policy(self, ip_address: IPAddress) -> bool:
        """Return True if the IP address is allowed to connect."""
        matched = any(ip_address in network for network in self.networks)
        if self.default_action is AccessListAction.ALLOW:
            return matched
        return not matched
