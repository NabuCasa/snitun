"""Public proxy interface with SNI."""
import asyncio
from contextlib import suppress
import logging

from ..exceptions import (MultiplexerTransportClose, MultiplexerTransportError,
                          ParseSNIError)
from .sni import parse_tls_sni

_LOGGER = logging.getLogger(__name__)


class SNIProxy:
    """SNI Proxy class."""

    def __init__(self, peer_manager, host=None, port=None):
        """Initialize SNI Proxy interface."""
        self._peer_manager = peer_manager
        self._loop = asyncio.get_event_loop()
        self._host = host
        self._port = port or 443
        self._server = None

    async def start(self):
        """Start Proxy server."""
        self._server = await asyncio.start_server(
            self._handle_connection, host=self._host, port=self._port)

        self._loop.create_task(self._server.serve_forever())

    async def stop(self):
        """Stop proxy server."""
        self._server.close()
        await self._server.wait_closed()

    async def _handle_connection(self, reader, writer):
        """Internal handler for incoming requests."""
        client_hello = await reader.read(1024)

        try:
            # Read Hostname
            try:
                hostname = parse_tls_sni(client_hello)
            except ParseSNIError:
                _LOGGER.waring(
                    "Receive invalid ClientHello on public Interface")
                return

            # Peer available?
            if hostname not in self._peer_manager:
                _LOGGER.warning("Hostname %s not connected", hostname)
                return
            multiplexer = self._peer_manager[hostname].multiplexer

            _LOGGER.debug("Start processing for hostname %", hostname)
            await self._proxy_peer(multiplexer, client_hello, reader, writer)

        finally:
            with suppress(OSError):
                writer.close()

    async def _proxy_peer(self, multiplexer, client_hello, reader, writer):
        """Proxy data between end points."""
        transport = writer.transport
        from_proxy = None
        from_peer = None

        # Open multiplexer channel
        try:
            channel = multiplexer.create_channel()
            await channel.write(client_hello)
        except MultiplexerTransportError:
            _LOGGER.error("Transport to peer fails")
            return

        try:
            # Process stream into multiplexer
            while not transport.is_closing():
                if not from_proxy:
                    from_proxy = self._loop.create_task(reader.read(4096))
                if not from_peer:
                    from_peer = self._loop.create_task(channel.read())

                # Wait until data need to be processed
                await asyncio.wait([from_proxy, from_peer],
                                   return_when=asyncio.FIRST_COMPLETED)

                # From proxy
                if from_proxy.done():
                    if from_peer.exception():
                        raise from_peer.exception()

                    await channel.write(from_proxy.result())
                    from_proxy = None

                # From peer
                if from_peer.done():
                    if from_peer.exception():
                        raise from_peer.exception()

                    writer.write(from_peer.result())
                    from_peer = None

        except MultiplexerTransportError:
            _LOGGER.debug("Multiplex Transport Error for %s", channel.uuid)
            await multiplexer.delete_channel(channel)

        except MultiplexerTransportClose:
            _LOGGER.debug("Peer close connection for %s", channel.uuid)

        finally:
            if from_peer and not from_peer.done():
                from_peer.close()
            if from_proxy and not from_proxy.done():
                from_proxy.close()
