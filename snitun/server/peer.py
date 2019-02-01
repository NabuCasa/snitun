"""Represent a single Peer."""
import asyncio
import hashlib
import logging
import os
from typing import List

from ..exceptions import MultiplexerTransportDecrypt, SniTunChallengeError
from ..multiplexer.core import Multiplexer
from ..multiplexer.crypto import CryptoTransport

_LOGGER = logging.getLogger(__name__)


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

    @property
    def is_ready(self) -> bool:
        """Return true if the Peer is ready to process data."""
        if self._multiplexer is None:
            return False

        if self.multiplexer.wait().done():
            return False

        return True

    def policy_connection_whitelist(self, address):
        """Check if address is allow to connect and return boolean."""
        if not self._whitelist:
            return True

        return address in self._whitelist

    async def init_multiplexer_challenge(self, reader: asyncio.StreamReader,
                                         writer: asyncio.StreamWriter) -> None:
        """Initialize multiplexer."""
        try:
            token = hashlib.sha256(os.urandom(40)).digest()
            writer.write(self._crypto.encrypt(token))
            await writer.drain()

            data = await reader.readexactly(32)
            data = self._crypto.decrypt(data)

            # Check Token
            assert hashlib.sha256(token).digest() == data

        except (asyncio.IncompleteReadError, MultiplexerTransportDecrypt,
                AssertionError, OSError):
            _LOGGER.warning("Wrong challenge from peer")
            raise SniTunChallengeError()

        # Start Multiplexer
        self._multiplexer = Multiplexer(self._crypto, reader, writer)

    def wait_disconnect(self) -> None:
        """Wait until peer is disconnected.

        Return awaitable object.
        """
        if not self._multiplexer:
            raise RuntimeError("No Transport initialize for peer")

        return self._multiplexer.wait()
