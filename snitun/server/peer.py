"""Represent a single Peer."""
from typing import List

from ..multiplexer.core import Multiplexer
from ..multiplexer.crypto import CryptoTransport


class Peer:
    """Representation of a Peer."""

    def __init__(self, hostname: str, whitelist: List[str], aes_key: bytes,
                 aes_iv: bytes):
        """Initialize a Peer."""
        self._hostname = hostname
        self._whitelist = whitelist
        self._multiplexer = None
        self._crypto = CryptoTransport(aes_key, aes_iv)

    @property
    def hostname(self) -> str:
        """Return his hostname."""
        return self._hostname

    @property
    def multiplexer(self) -> Multiplexer:
        """Return Multiplexer object."""
        return self._multiplexer

    def policy_connection_whitelist(self, address):
        """Check if address is allow to connect and return boolean."""
        if not self._whitelist:
            return True

        return address in self._whitelist

    def init_multiplexer(self, reader, writer) -> None:
        """Initialize multiplexer."""
        self._multiplexer = Multiplexer(self._crypto, reader, writer)

    async def wait_disconnect(self) -> None:
        """Wait until peer is disconnected."""
        if not self._multiplexer:
            raise RuntimeError("No Transport initialize for peer")

        await self._multiplexer.wait()
