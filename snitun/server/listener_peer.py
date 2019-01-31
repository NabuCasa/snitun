"""Public peer interface."""
import asyncio
from contextlib import suppress
import logging

from ..multiplexer.core import Multiplexer
from ..exceptions import (MultiplexerTransportClose, MultiplexerTransportError,
                          ParseSNIError)

_LOGGER = logging.getLogger(__name__)


class PeerListener:
    """Peer Listener class."""

    def __init__(self, peer_manager, host=None, port=None):
        """Initialize SNI Proxy interface."""
        self._peer_manager = peer_manager
        self._host = host
        self._port = port or 80
        self._server = None

    async def start(self):
        """Start peer server."""
        self._server = await asyncio.start_server(
            self._handle_connection, host=self._host, port=self._port)

    async def stop(self):
        """Stop peer server."""
        self._server.close()
        await self._server.wait_closed()

    async def _handle_connection(self, reader, writer):
        """Internal handler for incoming requests."""
