"""SniTun client for server connection."""
import asyncio
import hashlib
import logging
from typing import Optional

import async_timeout

from ..exceptions import (
    MultiplexerTransportDecrypt,
    MultiplexerTransportError,
    SniTunConnectionError,
)
from ..multiplexer.core import Multiplexer
from ..multiplexer.crypto import CryptoTransport
from .connector import Connector

_LOGGER = logging.getLogger(__name__)


class ClientPeer:
    """Client to SniTun Server."""

    def __init__(self, snitun_host: str, snitun_port=None):
        """Initialize ClientPeer connector."""
        self._multiplexer = None
        self._loop = asyncio.get_event_loop()
        self._snitun_host = snitun_host
        self._snitun_port = snitun_port or 8080

    @property
    def is_connected(self) -> bool:
        """Return true, if a connection exists."""
        return self._multiplexer is not None

    def wait(self) -> asyncio.Task:
        """Block until connection to peer is closed."""
        if not self._multiplexer:
            raise RuntimeError("No SniTun connection available")
        return self._multiplexer.wait()

    async def start(
        self,
        connector: Connector,
        fernet_token: bytes,
        aes_key: bytes,
        aes_iv: bytes,
        throttling: Optional[int] = None,
    ) -> None:
        """Connect an start ClientPeer."""
        if self._multiplexer:
            raise RuntimeError("SniTun connection available")

        # Connect to SniTun server
        try:
            reader, writer = await asyncio.open_connection(
                host=self._snitun_host, port=self._snitun_port
            )
        except OSError:
            _LOGGER.error(
                "Can't connect to SniTun server %s:%s",
                self._snitun_host,
                self._snitun_port,
            )
            raise SniTunConnectionError()

        # Send fernet token
        writer.write(fernet_token)
        await writer.drain()

        # Challenge/Response
        crypto = CryptoTransport(aes_key, aes_iv)
        try:
            challenge = await reader.readexactly(32)
            answer = hashlib.sha256(crypto.decrypt(challenge)).digest()

            writer.write(crypto.encrypt(answer))
            await writer.drain()
        except (MultiplexerTransportDecrypt, asyncio.IncompleteReadError, OSError):
            _LOGGER.error("Challenge/Response error with SniTun server")
            raise SniTunConnectionError()

        # Run multiplexer
        self._multiplexer = Multiplexer(
            crypto,
            reader,
            writer,
            new_connections=connector.handler,
            throttling=throttling,
        )

        # Task a process for pings/cleanups
        self._loop.create_task(self._handler())

    async def stop(self) -> None:
        """Stop connection to SniTun server."""
        if not self._multiplexer:
            raise RuntimeError("No SniTun connection available")
        await self._multiplexer.shutdown()

    async def _handler(self) -> None:
        """Wait until connection is closed."""
        try:
            while self._multiplexer.is_connected:
                try:
                    async with async_timeout.timeout(50):
                        await self._multiplexer.wait()
                except asyncio.TimeoutError:
                    await self._multiplexer.ping()

        except MultiplexerTransportError:
            pass

        finally:
            self._multiplexer = None
