"""SniTun client for server connection."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys

from ..exceptions import (
    MultiplexerTransportDecrypt,
    MultiplexerTransportError,
    SniTunConnectionError,
)
from ..multiplexer.core import Multiplexer
from ..multiplexer.crypto import CryptoTransport
from ..utils.asyncio import asyncio_timeout, make_task_waiter_future
from .connector import Connector

_LOGGER = logging.getLogger(__name__)

CONNECTION_TIMEOUT = 60


class ClientPeer:
    """Client to SniTun Server."""

    def __init__(self, snitun_host: str, snitun_port: int | None = None) -> None:
        """Initialize ClientPeer connector."""
        self._multiplexer = None
        self._loop = asyncio.get_event_loop()
        self._snitun_host = snitun_host
        self._snitun_port = snitun_port or 8080
        self._handler_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        """Return true, if a connection exists."""
        return self._multiplexer is not None

    def wait(self) -> asyncio.Task:
        """Block until connection to peer is closed."""
        if not self._multiplexer:
            raise RuntimeError("No SniTun connection available")
        # Wait until the handler task is done
        # as we know the connection is closed
        return make_task_waiter_future(self._handler_task)

    async def start(
        self,
        connector: Connector,
        fernet_token: bytes,
        aes_key: bytes,
        aes_iv: bytes,
        throttling: int | None = None,
    ) -> None:
        """Connect an start ClientPeer."""
        if self._multiplexer:
            raise RuntimeError("SniTun connection available")

        # Connect to SniTun server
        _LOGGER.debug(
            "Opening connection to %s:%s",
            self._snitun_host,
            self._snitun_port,
        )
        try:
            async with asyncio_timeout.timeout(CONNECTION_TIMEOUT):
                reader, writer = await asyncio.open_connection(
                    host=self._snitun_host,
                    port=self._snitun_port,
                )
        except TimeoutError:
            raise SniTunConnectionError(
                "Connection timeout for SniTun server "
                f"{self._snitun_host}:{self._snitun_port}",
            ) from None
        except OSError as err:
            raise SniTunConnectionError(
                "Can't connect to SniTun server "
                f"{self._snitun_host}:{self._snitun_port} with: {err}",
            ) from err

        # Send fernet token
        writer.write(fernet_token)
        try:
            async with asyncio_timeout.timeout(CONNECTION_TIMEOUT):
                await writer.drain()
        except TimeoutError:
            raise SniTunConnectionError(
                "Timeout for writting connection token",
            ) from None

        # Challenge/Response
        crypto = CryptoTransport(aes_key, aes_iv)
        try:
            async with asyncio_timeout.timeout(CONNECTION_TIMEOUT):
                challenge = await reader.readexactly(32)
                answer = hashlib.sha256(crypto.decrypt(challenge)).digest()

                writer.write(crypto.encrypt(answer))
                await writer.drain()
        except TimeoutError:
            raise SniTunConnectionError(
                "Challenge/Response timeout error to SniTun server",
            ) from None
        except (
            MultiplexerTransportDecrypt,
            asyncio.IncompleteReadError,
            OSError,
        ) as err:
            raise SniTunConnectionError(
                f"Challenge/Response error with SniTun server ({err})",
            ) from err

        # Run multiplexer
        self._multiplexer = Multiplexer(
            crypto,
            reader,
            writer,
            new_connections=connector.handler,
            throttling=throttling,
        )

        # Task a process for pings/cleanups
        assert not self._handler_task or self._handler_task.done(), (
            "SniTun connection already running"
        )
        self._handler_task = self._loop.create_task(self._handler())

    async def stop(self) -> None:
        """Stop connection to SniTun server."""
        if not self._multiplexer:
            raise RuntimeError("No SniTun connection available")
        self._multiplexer.shutdown()
        await self._multiplexer.wait()
        await self._stop_handler()

    async def _stop_handler(self) -> None:
        """Stop the handler."""
        self._handler_task.cancel()
        try:
            await self._handler_task
        except asyncio.CancelledError:
            # Don't swallow cancellation
            if (
                sys.version_info >= (3, 11)
                and (current_task := asyncio.current_task())
                and current_task.cancelling()
            ):
                raise
        finally:
            self._handler_task = None

    async def _handler(self) -> None:
        """Wait until connection is closed."""

        async def _wait_with_timeout() -> None:
            try:
                async with asyncio_timeout.timeout(50):
                    await self._multiplexer.wait()
            except TimeoutError:
                await self._multiplexer.ping()

        try:
            while self._multiplexer.is_connected:
                await _wait_with_timeout()

        except MultiplexerTransportError:
            pass

        finally:
            self._multiplexer.shutdown()
            self._multiplexer = None
