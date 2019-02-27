"""Helper for handle aiohttp internal server."""
import socket
import ssl

from aiohttp.web import AppRunner, SockSite

from ..client.client_peer import ClientPeer
from ..client.connector import Connector


class SniTunClientAioHttp:
    """Help to handle a internal aiohttp app runner."""

    def __init__(self,
                 runner: AppRunner,
                 context: ssl.SSLContext,
                 snitun_server: str,
                 snitun_port=None):
        """Initialize SniTunClient with aiohttp."""
        self._connector = None
        self._client = ClientPeer(snitun_server, snitun_port)
        self._socket = socket.socket()

        # Init interface
        self._socket.setblocking(False)
        self._socket.bind(("127.0.0.1", 0))
        self._site = SockSite(runner, self._socket, ssl_context=context)

    @property
    def whitelist(self):
        """Return whitelist from connector."""
        if self._connector:
            return self._connector.whitelist
        return set()

    async def start(self, whitelist=False):
        """Start internal server."""
        await self._site.start()

        host, port = self._socket.getsockname()[:2]
        self._connector = Connector(host, port, whitelist)

    async def stop(self):
        """Stop internal server."""
        await self.disconnect()
        await self._site.start()

    async def connect(self, fernet_key, aes_key, aes_iv):
        """Connect to SniTun server."""
        if self._client.is_connected:
            return
        await self._client.start(self._connector, fernet_key, aes_key, aes_iv)

    async def disconnect(self):
        """Disconnect from SniTun server."""
        if not self._client.is_connected:
            return
        await self._client.stop()
