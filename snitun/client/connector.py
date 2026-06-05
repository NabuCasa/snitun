"""Connector to end resource."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Callable, Coroutine
from contextlib import suppress
import ipaddress
from ipaddress import IPv4Address
import logging
from ssl import SSLContext, SSLError
from typing import Any

from ..exceptions import MultiplexerTransportClose, MultiplexerTransportError
from ..multiplexer.channel import ChannelFlowControlBase, MultiplexerChannel
from ..multiplexer.core import Multiplexer
from ..multiplexer.transport import ChannelTransport

_LOGGER = logging.getLogger(__name__)


class Connector(ABC):
    """Abstract connector to an end resource.

    A connector receives new channels from the multiplexer (via
    :meth:`handler`), applies the shared whitelist policy and then
    delegates the actual bridging of the channel to a concrete
    implementation through :meth:`_handle_connection`.

    Two implementations are provided:

    * :class:`TransportConnector` wraps the channel in a
      :class:`~snitun.multiplexer.transport.ChannelTransport` and upgrades
      it to TLS, connecting an ``asyncio.Protocol`` (e.g. an aiohttp
      ``RequestHandler``) directly to the channel without a loop back
      connection.
    * :class:`EndpointConnector` forwards the traffic of the channel to
      another ``IP:port`` over a plain TCP connection (the original
      snitun behavior).
    """

    def __init__(self, whitelist: bool = False) -> None:
        """Initialize Connector."""
        self._whitelist: set[IPv4Address] = set()
        self._whitelist_enabled = whitelist

    @property
    def whitelist(self) -> set[IPv4Address]:
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
        # Check policy
        if not self._whitelist_policy(channel.ip_address):
            _LOGGER.warning("Block request from %s per policy", channel.ip_address)
            multiplexer.delete_channel(channel)
            return

        await self._handle_connection(multiplexer, channel)

    @abstractmethod
    async def _handle_connection(
        self,
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Bridge an accepted channel to the end resource."""


class TransportConnector(Connector):
    """Connector that bridges a channel directly to a protocol via TLS.

    This is the loop-back-free connector introduced to eliminate the
    intermediate localhost TCP connection. Instead of opening a socket to
    an end host, it wraps the multiplexer channel in a
    :class:`~snitun.multiplexer.transport.ChannelTransport` and upgrades it
    to TLS, connecting the protocol produced by ``protocol_factory``
    (e.g. an aiohttp ``RequestHandler``) directly to the channel.

    Protocol contract: the protocol returned by ``protocol_factory`` MUST
    tolerate ``connection_lost()`` being called more than once (i.e. it
    must be reentrant / idempotent). On teardown the protocol can receive
    ``connection_lost()`` both from the SSLProtocol cascade and directly
    from :meth:`ConnectorHandler.start` (see the comment there for why the
    direct call is required for the sendfile case). aiohttp's
    ``RequestHandler`` satisfies this; a custom protocol must too.
    """

    def __init__(
        self,
        protocol_factory: Callable[[], asyncio.Protocol],
        ssl_context: SSLContext,
        whitelist: bool = False,
    ) -> None:
        """Initialize TransportConnector.

        protocol_factory must produce a protocol whose connection_lost()
        is safe to call more than once; see the class docstring.
        """
        super().__init__(whitelist)
        self._protocol_factory = protocol_factory
        self._ssl_context = ssl_context

    async def _handle_connection(
        self,
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Bridge an accepted channel to a TLS protocol."""
        _LOGGER.debug("New connection from %s", channel.ip_address)

        loop = asyncio.get_running_loop()
        transport = ChannelTransport(channel, multiplexer)

        await ConnectorHandler(loop, multiplexer, channel, transport).start(
            self._protocol_factory,
            self._ssl_context,
        )


class EndpointConnector(Connector):
    """Connector that forwards channel traffic to another IP/port over TCP.

    This is the original snitun behavior: each multiplexer channel is
    bridged to a plain TCP connection opened to ``end_host:end_port``.
    """

    def __init__(
        self,
        end_host: str,
        end_port: int | str | None = None,
        whitelist: bool = False,
        endpoint_connection_error_callback: Callable[[], Coroutine[Any, Any, None]]
        | None = None,
    ) -> None:
        """Initialize EndpointConnector."""
        super().__init__(whitelist)
        self._end_host = end_host
        self._end_port = end_port or 443
        self._endpoint_connection_error_callback = endpoint_connection_error_callback

    async def _handle_connection(
        self,
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Bridge an accepted channel to a TCP endpoint."""
        _LOGGER.debug(
            "Receive from %s a request for %s",
            channel.ip_address,
            self._end_host,
        )

        loop = asyncio.get_running_loop()
        await EndpointConnectorHandler(loop, channel).start(
            multiplexer,
            self._end_host,
            self._end_port,
            self._endpoint_connection_error_callback,
        )


class ConnectorHandler:
    """Handle connection to endpoint.

    Bridges channel-level flow control to the SSL/app protocol layer.

    Unlike EndpointConnectorHandler (TCP forwarding), this class does NOT
    inherit from ChannelFlowControlBase because it has no read/write loop
    to pause with a future. Instead, the ChannelTransport owns the reader
    task, and this handler translates channel backpressure signals into
    pause_protocol() / resume_protocol() calls on the transport, which
    in turn call SSLProtocol.pause_writing() / resume_writing().
    """

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
        self._multiplexer.delete_channel(channel)
        await self._transport.stop_reader()

    async def start(
        self,
        protocol_factory: Callable[[], asyncio.Protocol],
        ssl_context: SSLContext,
    ) -> None:
        """Start handler."""
        channel = self._channel
        channel.set_pause_resume_reader_callback(self._pause_resume_reader_callback)
        self._transport.start_reader()
        # The request_handler is the aiohttp RequestHandler (or any other protocol)
        # that is generated from the protocol_factory that
        # was passed in the constructor.
        protocol = protocol_factory()

        # Upgrade the transport to TLS
        try:
            new_transport = await self._loop.start_tls(
                self._transport,
                protocol,
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
        #
        # When the channel closes, ChannelTransport._force_close()
        # schedules SSLProtocol.connection_lost() via call_soon, which
        # cascades to the app protocol. We still call connection_lost
        # on the app protocol directly here because during sendfile,
        # SSLProtocol's cascade reaches _SendfileFallbackProtocol
        # instead of the app protocol. aiohttp's connection_lost is
        # reentrant so the double call in the normal case is safe.
        #
        # We intentionally do NOT call new_transport.close() — the
        # SSLProtocol is already torn down by connection_lost from
        # _force_close, and calling close() would start an SSL
        # shutdown that can never complete (the channel is closed so
        # the peer's close_notify never arrives).
        _LOGGER.info("Connected peer: %s (%s)", channel.ip_address, channel.id)
        exc: Exception | None = None
        try:
            protocol.connection_made(new_transport)
            await self._transport.wait_for_close()
        except Exception as err:  # noqa: BLE001
            # Serve boundary: deliver any terminal error to the protocol's
            # connection_lost() instead of leaking it out of the task.
            # CancelledError and other BaseExceptions intentionally propagate.
            exc = err
            _LOGGER.error(
                "Transport error for %s (%s): %s",
                channel.ip_address,
                channel.id,
                err,
            )
            self._multiplexer.delete_channel(channel)
        else:
            _LOGGER.debug(
                "Peer close connection for %s (%s)",
                channel.ip_address,
                channel.id,
            )
        # connection_lost is called exactly once, with the error (or None).
        protocol.connection_lost(exc)


class EndpointConnectorHandler(ChannelFlowControlBase):
    """Handle connection to a TCP endpoint.

    This is the original handler that forwards the traffic of a channel
    to another ``IP:port`` over a plain TCP connection.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        channel: MultiplexerChannel,
    ) -> None:
        """Initialize EndpointConnectorHandler."""
        super().__init__(loop)
        self._channel = channel

    async def start(
        self,
        multiplexer: Multiplexer,
        end_host: str,
        end_port: int | str,
        endpoint_connection_error_callback: Callable[[], Coroutine[Any, Any, None]]
        | None = None,
    ) -> None:
        """Start handler."""
        channel = self._channel
        channel.set_pause_resume_reader_callback(self._pause_resume_reader_callback)
        # Open connection to endpoint
        try:
            reader, writer = await asyncio.open_connection(host=end_host, port=end_port)
        except OSError:
            _LOGGER.error(
                "Can't connect to endpoint %s:%s",
                end_host,
                end_port,
            )
            multiplexer.delete_channel(channel)
            if endpoint_connection_error_callback:
                await endpoint_connection_error_callback()
            return

        from_endpoint: asyncio.Future[None] | asyncio.Task[bytes] | None = None
        from_peer: asyncio.Task[bytes] | None = None
        try:
            # Process stream from multiplexer
            while not writer.transport.is_closing():
                if not from_endpoint:
                    # If the multiplexer channel queue is under water, pause the reader
                    # by waiting for the future to be set, once the queue is not under
                    # water the future will be set and cleared to resume the reader
                    from_endpoint = self._pause_future or self._loop.create_task(
                        reader.read(4096),  # type: ignore[arg-type]
                    )
                if not from_peer:
                    from_peer = self._loop.create_task(channel.read())

                # Wait until data need to be processed
                await asyncio.wait(
                    [from_endpoint, from_peer],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # From proxy
                if from_endpoint.done():
                    if from_endpoint_exc := from_endpoint.exception():
                        raise from_endpoint_exc

                    if (from_endpoint_result := from_endpoint.result()) is not None:
                        await channel.write(from_endpoint_result)
                    from_endpoint = None

                # From peer
                if from_peer.done():
                    if from_peer_exc := from_peer.exception():
                        raise from_peer_exc

                    writer.write(from_peer.result())
                    from_peer = None

                    # Flush buffer
                    await writer.drain()

        except (MultiplexerTransportError, OSError, RuntimeError):
            _LOGGER.debug("Transport closed by endpoint for %s", channel.id)
            multiplexer.delete_channel(channel)

        except MultiplexerTransportClose:
            _LOGGER.debug("Peer close connection for %s", channel.id)

        finally:
            # Cleanup peer reader
            if from_peer:
                if not from_peer.done():
                    from_peer.cancel()
                else:
                    # Avoid exception was never retrieved
                    from_peer.exception()

            # Cleanup endpoint reader
            if from_endpoint and not from_endpoint.done():
                from_endpoint.cancel()

            # Close Transport
            if not writer.transport.is_closing():
                with suppress(OSError):
                    writer.close()
