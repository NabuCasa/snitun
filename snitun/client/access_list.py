"""Access control list for connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address


class AccessListAction(StrEnum):
    """Action of an :class:`AccessList`.

    The action defines how the IPs in the list are treated:

    * ``ALLOW`` (old behavior): only the IPs in the list may connect, every
      other IP is blocked.
    * ``BLOCK``: the IPs in the list are blocked, every other IP may connect.
    """

    ALLOW = "allow"
    BLOCK = "block"


@dataclass(slots=True)
class AccessList:
    """Per-IP access policy for a connector.

    ``default_action`` selects the policy applied to the IPs in ``ips`` (see
    :class:`AccessListAction`). With the default ``ALLOW`` action an empty list
    blocks everyone; with ``BLOCK`` an empty list allows everyone.
    """

    default_action: AccessListAction = AccessListAction.ALLOW
    ips: set[IPv4Address | IPv6Address] = field(default_factory=set)

    def add(self, ip_address: IPv4Address | IPv6Address) -> None:
        """Add an IP address to the list."""
        self.ips.add(ip_address)

    def remove(self, ip_address: IPv4Address | IPv6Address) -> None:
        """Remove an IP address from the list (no error if absent)."""
        self.ips.discard(ip_address)

    def check_policy(self, ip_address: IPv4Address | IPv6Address) -> bool:
        """Return True if the IP address is allowed to connect."""
        if self.default_action is AccessListAction.ALLOW:
            return ip_address in self.ips
        return ip_address not in self.ips
