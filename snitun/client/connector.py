"""Connector to end resource."""

from __future__ import annotations

import asyncio
import asyncio.sslproto
from collections.abc import Callable
from contextlib import suppress
import ipaddress
import logging
from ssl import SSLContext, SSLError
from typing import TYPE_CHECKING

from ..exceptions import MultiplexerTransportError
from ..multiplexer.channel import MultiplexerChannel
from ..multiplexer.core import Multiplexer
from ..multiplexer.transport import ChannelTransport

if TYPE_CHECKING:
    from aiohttp.web import RequestHandler

_LOGGER = logging.getLogger(__name__)


class Connector:
    """Connector to end resource."""

    def __init__(
        self,
        protocol_factory: Callable[[], RequestHandler],
        ssl_context: SSLContext,
        whitelist: bool = False,
    ) -> None:
        """Initialize Connector."""
        self._loop = asyncio.get_running_loop()
        self._whitelist: set[ipaddress.IPv4Address] = set()
        self._whitelist_enabled = whitelist
        self._protocol_factory = protocol_factory
        self._ssl_context = ssl_context

    @property
    def whitelist(self) -> set:
        """Allow to block requests per IP Return None or access to a set."""
        return self._whitelist

    def _whitelist_policy(self, ip_address: ipaddress.IPv4Address) -> bool:
        """Return True if the ip address can access to endpoint."""
        return not self._whitelist_enabled or ip_address in self._whitelist

    async def handler(
        self,
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Handle new connection from SNIProxy."""
        _LOGGER.debug("New connection from %s", channel.ip_address)

        # Check policy
        if not self._whitelist_policy(channel.ip_address):
            _LOGGER.warning("Block request from %s per policy", channel.ip_address)
            await multiplexer.delete_channel(channel)
            return

        transport = ChannelTransport(channel, multiplexer)

        await ConnectorHandler(self._loop, multiplexer, channel, transport).start(
            self._protocol_factory,
            self._ssl_context,
        )


class ConnectorHandler:
    """Handle connection to endpoint."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
        transport: ChannelTransport,
    ) -> None:
        """Initialize ConnectorHandler."""
        self._loop = loop
        self._multiplexer = multiplexer
        self._channel = channel
        self._transport = transport

    def _pause_resume_reader_callback(self, pause: bool) -> None:
        """Pause and resume reader."""
        _LOGGER.debug(
            "%s reader for %s (%s)",
            "Pause" if pause else "Resume",
            self._channel.ip_address,
            self._channel.id,
        )
        if pause:
            self._transport.pause_protocol()
        else:
            self._transport.resume_protocol()

    async def _fail_to_start_tls(self, ex: Exception | None) -> None:
        """Handle failure to start TLS."""
        channel = self._channel
        _LOGGER.debug(
            "Cannot start TLS for %s (%s): %s",
            channel.ip_address,
            channel.id,
            ex,
        )
        with suppress(MultiplexerTransportError):
            await self._multiplexer.delete_channel(channel)
        await self._transport.stop_reader()

    async def start(
        self,
        protocol_factory: Callable[[], RequestHandler],
        ssl_context: SSLContext,
    ) -> None:
        """Start handler."""
        channel = self._channel
        channel.set_pause_resume_reader_callback(self._pause_resume_reader_callback)
        self._transport.start_reader()
        # The request_handler is the aiohttp RequestHandler
        # that is generated from the protocol_factory that
        # was passed in the constructor.
        request_handler_protocol = protocol_factory()

        # Upgrade the transport to TLS
        try:
            new_transport = await self._loop.start_tls(
                self._transport,
                request_handler_protocol,
                ssl_context,
                server_side=True,
            )
        except (OSError, SSLError) as ex:
            # This can can be just about any error, but mostly likely it's a TLS error
            # or the connection gets dropped in the middle of the handshake
            await self._fail_to_start_tls(ex)
            return

        if not new_transport:
            await self._fail_to_start_tls(None)
            return

        # Now that we have the connection upgraded to TLS, we can
        # start the request handler and serve the connection.
        _LOGGER.info("Connected peer: %s (%s)", channel.ip_address, channel.id)
        try:
            request_handler_protocol.connection_made(new_transport)
            await self._transport.wait_for_close()
        except Exception as ex:  # noqa: BLE001
            # Make sure we catch any exception that might be raised
            # so it gets feed back to connection_lost
            _LOGGER.error(
                "Transport error for %s (%s): %s",
                channel.ip_address,
                channel.id,
                ex,
            )
            with suppress(MultiplexerTransportError):
                await self._multiplexer.delete_channel(channel)
            request_handler_protocol.connection_lost(ex)
        else:
            _LOGGER.debug(
                "Peer close connection for %s (%s)",
                channel.ip_address,
                channel.id,
            )
            request_handler_protocol.connection_lost(None)
        finally:
            new_transport.close()
