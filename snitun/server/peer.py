"""Represent a single Peer."""
import asyncio
from datetime import datetime
import hashlib
import logging
import os
from typing import Optional

from ..exceptions import MultiplexerTransportDecrypt, SniTunChallengeError
from ..multiplexer.core import Multiplexer
from ..multiplexer.crypto import CryptoTransport

_LOGGER = logging.getLogger(__name__)


class Peer:
    """Representation of a Peer."""

    def __init__(
        self,
        hostname: str,
        valid: datetime,
        aes_key: bytes,
        aes_iv: bytes,
        throttling: Optional[int] = None,
    ):
        """Initialize a Peer."""
        self._hostname = hostname
        self._valid = valid
        self._throttling = throttling
        self._multiplexer = None
        self._crypto = CryptoTransport(aes_key, aes_iv)

    @property
    def hostname(self) -> str:
        """Return his hostname."""
        return self._hostname

    @property
    def is_connected(self) -> bool:
        """Return True if we are connected to peer."""
        if not self._multiplexer:
            return False
        return self._multiplexer.is_connected

    @property
    def is_valid(self) -> bool:
        """Return True if the peer is valid."""
        return self._valid > datetime.utcnow()

    @property
    def multiplexer(self) -> Optional[Multiplexer]:
        """Return Multiplexer object."""
        return self._multiplexer

    @property
    def is_ready(self) -> bool:
        """Return true if the Peer is ready to process data."""
        if self.multiplexer is None:
            return False
        if not self.multiplexer.is_connected:
            return False
        return True

    async def init_multiplexer_challenge(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Initialize multiplexer."""
        try:
            token = hashlib.sha256(os.urandom(40)).digest()
            writer.write(self._crypto.encrypt(token))
            await writer.drain()

            data = await reader.readexactly(32)
            data = self._crypto.decrypt(data)

            # Check Token
            assert hashlib.sha256(token).digest() == data

        except (
            asyncio.IncompleteReadError,
            MultiplexerTransportDecrypt,
            AssertionError,
            OSError,
        ):
            _LOGGER.warning("Wrong challenge from peer")
            raise SniTunChallengeError()

        # Start Multiplexer
        self._multiplexer = Multiplexer(
            self._crypto, reader, writer, throttling=self._throttling
        )

    def wait_disconnect(self) -> asyncio.Task:
        """Wait until peer is disconnected.

        Return awaitable object.
        """
        if not self._multiplexer:
            raise RuntimeError("No Transport initialize for peer")

        return self._multiplexer.wait()
