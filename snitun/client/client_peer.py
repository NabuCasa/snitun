"""SniTun client for server connection."""
import asyncio
import hashlib
import logging

from .connector import Connector
from ..multiplexer.crypto import CryptoTransport
from ..multiplexer.core import Multiplexer
from ..exceptions import MultiplexerTransportDecrypt, SniTunConnectionError

_LOGGER = logging.getLogger(__name__)


class ClientPeer:
    """Client to SniTun Server."""

    def __init__(self, snitun_host: str, snitun_port=None):
        """Initialize ClientPeer connector."""
        self._multiplexer = None
        self._loop = asyncio.get_event_loop()
        self._snitun_host = snitun_host
        self._snitun_port = snitun_port or 8080

    async def start(self, connector: Connector, fernet_token: bytes,
                    aes_key: bytes, aes_iv: bytes) -> None:
        """Connect an start ClientPeer."""
        if self._multiplexer:
            raise RuntimeError("Connection available")

        # Connect to SniTun server
        try:
            reader, writer = await asyncio.open_connection(
                host=self._snitun_host, port=self._snitun_port)
        except OSError:
            _LOGGER.error("Can't connect to SniTun server %s:%s",
                          self._snitun_host, self._snitun_port)
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
        except (MultiplexerTransportDecrypt, asyncio.IncompleteReadError,
                OSError):
            _LOGGER.error("Challenge/Response error with SniTun server")
            raise SniTunConnectionError()

        self._multiplexer = Multiplexer(crypto, reader, writer,
                                        connector.handler)
        self._loop.create_task(self._handler())

    async def stop(self):
        """Stop connection to SniTun server."""
        if not self._multiplexer:
            raise RuntimeError("Connection available")

        await self._multiplexer.shutdown()

    async def _handler(self):
        """Wait until connection is closed."""
        try:
            await self._multiplexer.wait()
        finally:
            self._multiplexer = None
