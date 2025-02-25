"""Public proxy interface with SNI."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import ipaddress
import logging

from ..exceptions import (
    MultiplexerTransportError,
    ParseSNIError,
)
from ..multiplexer.channel import MultiplexerChannel
from ..multiplexer.core import Multiplexer
from ..utils.asyncio import (
    RangedTimeout,
    asyncio_timeout,
    create_eager_task,
)
from .peer_manager import PeerManager
from .sni import parse_tls_sni, payload_reader

_LOGGER = logging.getLogger(__name__)

PEER_TCP_SESSION_MIN_TIMEOUT = 90
PEER_TCP_SESSION_MAX_TIMEOUT = 120


class SNIProxy:
    """SNI Proxy class."""

    def __init__(
        self,
        peer_manager: PeerManager,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        """Initialize SNI Proxy interface."""
        self._peer_manager = peer_manager
        self._loop = asyncio.get_event_loop()
        self._host = host
        self._port = port or 443
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start Proxy server."""
        self._server = await asyncio.start_server(
            self.handle_connection,
            host=self._host,
            port=self._port,
        )

    async def stop(self) -> None:
        """Stop proxy server."""
        assert self._server is not None, "Server not started"
        self._server.close()
        await self._server.wait_closed()

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        data: bytes | None = None,
        sni: str | None = None,
    ) -> None:
        """Handle incoming requests."""
        if data is None:
            try:
                async with asyncio_timeout.timeout(2):
                    client_hello = await payload_reader(reader)
            except TimeoutError:
                _LOGGER.warning("Abort SNI handshake")
                writer.close()
                return
            except OSError:
                return
        else:
            client_hello = data

        # Connection closed before data received
        if not client_hello:
            with suppress(OSError):
                writer.close()
            return

        try:
            # Read Hostname
            if sni is None:
                try:
                    hostname = parse_tls_sni(client_hello)
                except ParseSNIError:
                    _LOGGER.warning("Receive invalid ClientHello on public Interface")
                    return
            else:
                hostname = sni

            # Peer available?
            if not self._peer_manager.peer_available(hostname):
                _LOGGER.debug("Hostname %s not connected", hostname)
                return
            peer = self._peer_manager.get_peer(hostname)
            assert peer is not None, "Peer not found"
            # Proxy data over mutliplexer to client
            _LOGGER.debug("Processing for hostname %s started", hostname)
            assert peer.multiplexer is not None, "Multiplexer not initialized"
            await self._proxy_peer(peer.multiplexer, client_hello, reader, writer)

        finally:
            if not writer.transport.is_closing():
                with suppress(OSError):
                    writer.close()

    async def _proxy_peer(
        self,
        multiplexer: Multiplexer,
        client_hello: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Proxy data between end points."""
        try:
            ip_address = ipaddress.IPv4Address(writer.get_extra_info("peername")[0])
        except (TypeError, AttributeError):
            _LOGGER.error("Can't read source IP")
            return
        handler = ProxyPeerHandler(self._loop, ip_address)
        await handler.start(multiplexer, client_hello, reader, writer)


class ProxyPeerHandler:
    """Proxy Peer Handler."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        ip_address: ipaddress.IPv4Address,
    ) -> None:
        """Initialize ProxyPeerHandler."""
        self._loop = loop
        self._pause_future: asyncio.Future[None] | None = None
        self._ip_address = ip_address
        self._channel: MultiplexerChannel | None = None
        self._peer_task: asyncio.Task[None] | None = None
        self._proxy_task: asyncio.Task[None] | None = None
        self._ranged_timeout = RangedTimeout(
            PEER_TCP_SESSION_MIN_TIMEOUT,
            PEER_TCP_SESSION_MAX_TIMEOUT,
            self._on_timeout,
        )
        self._multiplexer: Multiplexer | None = None

    def _on_timeout(self) -> None:
        """Handle timeout."""
        assert self._channel is not None, "Channel not initialized"
        assert self._proxy_task is not None, "Proxy task not initialized"
        _LOGGER.debug("Close TCP session after timeout for %s", self._channel.id)
        self._proxy_task.cancel()

    def _pause_resume_reader_callback(self, pause: bool) -> None:
        """Pause and resume reader."""
        assert self._channel is not None, "Channel not initialized"
        if pause:
            _LOGGER.debug(
                "Pause reader for %s (%s)",
                self._ip_address,
                self._channel.id,
            )
            self._pause_future = self._loop.create_future()
        else:
            _LOGGER.debug(
                "Resuming reader for %s (%s)",
                self._ip_address,
                self._channel.id,
            )
            assert self._pause_future is not None, "Cannot resume non paused connection"
            self._pause_future.set_result(None)
            self._pause_future = None

    async def start(
        self,
        multiplexer: Multiplexer,
        client_hello: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Start handler."""
        ip_address = self._ip_address
        # Open multiplexer channel
        try:
            self._channel = await multiplexer.create_channel(
                ip_address,
                self._pause_resume_reader_callback,
            )
        except MultiplexerTransportError:
            _LOGGER.error("New transport channel to peer fails")
            return

        self._peer_task = self._loop.create_task(self._peer_loop(writer))
        self._proxy_task = self._loop.create_task(
            self._proxy_loop(reader, client_hello),
        )
        await asyncio.wait((self._proxy_task,))
        self._peer_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._peer_task

    async def _peer_loop(self, writer: asyncio.StreamWriter) -> None:
        """Read from peer loop."""
        transport = writer.transport
        channel = self._channel
        assert channel is not None, "Channel not initialized"
        try:
            while not transport.is_closing():
                writer.write(await channel.read())
                await writer.drain()
                self._ranged_timeout.reschedule()
        except asyncio.CancelledError:
            _LOGGER.debug("Peer loop canceling")
            with suppress(OSError):
                writer.write_eof()
                await writer.drain()
            raise
        except (MultiplexerTransportError, OSError, RuntimeError, ConnectionResetError):
            _LOGGER.debug("Peer loop: transport was closed")
        finally:
            if not writer.transport.is_closing():
                with suppress(OSError):
                    writer.close()

    async def _proxy_loop(
        self,
        reader: asyncio.StreamReader,
        client_hello: bytes,
    ) -> None:
        """Write to peer loop."""
        channel = self._channel
        assert channel is not None, "Channel not initialized"
        assert self._multiplexer is not None, "Multiplexer not initialized"
        try:
            await channel.write(client_hello)
            while not channel.closing:
                # If the multiplexer channel queue is under water, pause the reader
                # by waiting for the future to be set, once the queue is not under
                # water the future will be set and cleared to resume the reader
                if self._pause_future:
                    await self._pause_future
                await channel.write(await reader.read(8192))
                self._ranged_timeout.reschedule()
        except (
            MultiplexerTransportError,
            OSError,
            RuntimeError,
            ConnectionResetError,
            asyncio.IncompleteReadError,
        ):
            _LOGGER.debug("Proxy loop: transport was closed")
        finally:
            with suppress(MultiplexerTransportError):
                await asyncio.shield(
                    create_eager_task(self._multiplexer.delete_channel(channel)),
                )
