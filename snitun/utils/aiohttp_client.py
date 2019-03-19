"""Helper for handle aiohttp internal server."""
import asyncio
from contextlib import suppress
import logging
import socket
import ssl
from typing import Optional

from aiohttp.web import AppRunner, SockSite

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
        snitun_port=None,
    ):
        """Initialize SniTunClient with aiohttp."""
        self._connector = None
        self._client = ClientPeer(snitun_server, snitun_port)
        self._socket = socket.socket()
        self._server_name = "{}:{}".format(snitun_server, snitun_port)

        # Init interface
        self._socket.setblocking(False)
        self._socket.bind(("127.0.0.1", 0))
        self._site = SockSite(runner, self._socket, ssl_context=context)

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

    async def start(self, whitelist: bool = False) -> None:
        """Start internal server."""
        await self._site.start()

        host, port = self._socket.getsockname()[:2]
        self._connector = Connector(host, port, whitelist)

        _LOGGER.info("AioHTTP snitun client started on %s:%s", host, port)

    async def stop(self) -> None:
        """Stop internal server."""
        await self.disconnect()
        with suppress(OSError):
            self._socket.close()

        with suppress(RuntimeError):
            # pylint: disable=protected-access
            self._site._runner._unreg_site(self._site)

        _LOGGER.info("AioHTTP snitun client closed")

    async def connect(
        self,
        fernet_key: bytes,
        aes_key: bytes,
        aes_iv: bytes,
        throttling: Optional[int] = None,
    ) -> None:
        """Connect to SniTun server."""
        if self._client.is_connected:
            return
        await self._client.start(
            self._connector, fernet_key, aes_key, aes_iv, throttling=throttling
        )
        _LOGGER.info("AioHTTP snitun client connected to: %s", self._server_name)

    async def disconnect(self) -> None:
        """Disconnect from SniTun server."""
        if not self._client.is_connected:
            return
        await self._client.stop()
        _LOGGER.info("AioHTTP snitun client disconnected from: %s", self._server_name)
