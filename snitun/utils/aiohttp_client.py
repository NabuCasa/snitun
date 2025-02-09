"""Helper for handle aiohttp internal server."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import logging
import ssl
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp.web import AppRunner

from ..client.client_peer import ClientPeer
from ..client.connector import Connector

_LOGGER = logging.getLogger(__name__)


class SniTunClientAioHttp:
    """Help to handle a internal aiohttp app runner."""

    def __init__(
        self,
        runner: AppRunner,
        context: ssl.SSLContext,
        snitun_server: str,
        snitun_port: int | None = None,
    ) -> None:
        """Initialize SniTunClient with aiohttp."""
        self._connector = None
        self._client = ClientPeer(snitun_server, snitun_port)
        self._server_name = f"{snitun_server}:{snitun_port}"
        # Init interface
        self._protocol_factory = runner.server
        self._ssl_context = context

    @property
    def is_connected(self) -> bool:
        """Return True if we are connected to snitun."""
        return self._client.is_connected

    @property
    def whitelist(self) -> set:
        """Return whitelist from connector."""
        if self._connector:
            return self._connector.whitelist
        return set()

    def wait(self) -> asyncio.Task:
        """Block until connection to snitun is closed."""
        return self._client.wait()

    async def start(
        self,
        whitelist: bool = False,
        endpoint_connection_error_callback: Coroutine[Any, Any, None] | None = None,
    ) -> None:
        """Start internal server."""
        self._connector = Connector(
            self._protocol_factory,
            self._ssl_context,
            whitelist,
            endpoint_connection_error_callback=endpoint_connection_error_callback,
        )
        _LOGGER.info("AioHTTP snitun client started")

    async def stop(self, *, wait: bool = False) -> None:  # noqa: ARG002
        """
        Stop internal server.

        Args:
            wait: wait for the socket to close.

            This argument is not used, as we can now stop without
            waiting.
        """
        await self.disconnect()
        _LOGGER.info("AioHTTP snitun client closed")

    async def connect(
        self,
        fernet_key: bytes,
        aes_key: bytes,
        aes_iv: bytes,
        throttling: int | None = None,
    ) -> None:
        """Connect to SniTun server."""
        if self._client.is_connected:
            return
        await self._client.start(
            self._connector,
            fernet_key,
            aes_key,
            aes_iv,
            throttling=throttling,
        )
        _LOGGER.info("AioHTTP snitun client connected to: %s", self._server_name)

    async def disconnect(self) -> None:
        """Disconnect from SniTun server."""
        if not self._client.is_connected:
            return
        await self._client.stop()
        _LOGGER.info("AioHTTP snitun client disconnected from: %s", self._server_name)
