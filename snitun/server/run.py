"""SniTun reference implementation."""
import asyncio
import logging
from typing import List, Optional

import async_timeout

from .listener_peer import PeerListener
from .listener_sni import SNIProxy
from .peer_manager import PeerManager

_LOGGER = logging.getLogger(__name__)


class SniTunServer:
    """SniTunServer helper class."""

    def __init__(
        self,
        fernet_keys: List[str],
        sni_port=None,
        sni_host=None,
        peer_port=None,
        peer_host=None,
        throttling: Optional[int] = None,
    ):
        """Initialize SniTun Server."""
        self._peers = PeerManager(fernet_keys, throttling=throttling)
        self._list_sni = SNIProxy(self._peers, host=sni_host, port=sni_port)
        self._list_peer = PeerListener(self._peers, host=peer_host, port=peer_port)

    @property
    def peers(self) -> PeerManager:
        """Return peer manager."""
        return self._peers

    def start(self):
        """Run server.

        Return coroutine.
        """
        return asyncio.wait([self._list_peer.start(), self._list_sni.start()])

    def stop(self):
        """Stop server.

        Return coroutine.
        """
        return asyncio.wait([self._list_peer.stop(), self._list_sni.stop()])


class SniTunServerSingle:
    """SniTunServer helper class."""

    def __init__(
        self,
        fernet_keys: List[str],
        host=None,
        port=None,
        throttling: Optional[int] = None,
    ):
        """Initialize SniTun Server."""
        self._loop = asyncio.get_event_loop()
        self._peers = PeerManager(fernet_keys, throttling=throttling)
        self._list_sni = SNIProxy(self._peers, host=host)
        self._list_peer = PeerListener(self._peers, host=host)
        self._host = host
        self._port = port or 443
        self._server = None

    @property
    def peers(self) -> PeerManager:
        """Return peer manager."""
        return self._peers

    async def start(self):
        """Run server."""
        self._server = await asyncio.start_server(
            self._handler, host=self._host, port=self._port
        )

    async def stop(self):
        """Stop server."""
        self._server.close()
        await self._server.wait_closed()

    async def _handler(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle incoming connection."""
        try:
            async with async_timeout.timeout(2):
                data = await reader.read(2048)
        except asyncio.TimeoutError:
            _LOGGER.warning("Abort connection initializing")
            writer.close()
            return
        except OSError:
            return

        # Connection closed / healty check
        if not data:
            writer.close()
            return

        # Select the correct handler for process data
        if data[0] == 0x16:
            self._loop.create_task(
                self._list_sni.handle_connection(reader, writer, data)
            )
        else:
            self._loop.create_task(
                self._list_peer.handle_connection(reader, writer, data)
            )
