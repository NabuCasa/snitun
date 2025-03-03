"""Connector to end resource."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import suppress
import ipaddress
from ipaddress import IPv4Address
import logging
from typing import Any

from ..exceptions import MultiplexerTransportClose, MultiplexerTransportError
from ..multiplexer.channel import ChannelFlowControlBase, MultiplexerChannel
from ..multiplexer.core import Multiplexer

_LOGGER = logging.getLogger(__name__)


class Connector:
    """Connector to end resource."""

    def __init__(
        self,
        end_host: str,
        end_port: int | None = None,
        whitelist: bool = False,
        endpoint_connection_error_callback: Callable[[], Coroutine[Any, Any, None]]
        | None = None,
    ) -> None:
        """Initialize Connector."""
        self._loop = asyncio.get_event_loop()
        self._end_host = end_host
        self._end_port = end_port or 443
        self._whitelist: set[IPv4Address] = set()
        self._whitelist_enabled = whitelist
        self._endpoint_connection_error_callback = endpoint_connection_error_callback

    @property
    def whitelist(self) -> set:
        """Allow to block requests per IP Return None or access to a set."""
        return self._whitelist

    def _whitelist_policy(self, ip_address: ipaddress.IPv4Address) -> bool:
        """Return True if the ip address can access to endpoint."""
        if self._whitelist_enabled:
            return ip_address in self._whitelist
        return True

    async def handler(
        self,
        multiplexer: Multiplexer,
        channel: MultiplexerChannel,
    ) -> None:
        """Handle new connection from SNIProxy."""
        _LOGGER.debug(
            "Receive from %s a request for %s",
            channel.ip_address,
            self._end_host,
        )

        # Check policy
        if not self._whitelist_policy(channel.ip_address):
            _LOGGER.warning("Block request from %s per policy", channel.ip_address)
            multiplexer.delete_channel(channel)
            return

        await ConnectorHandler(self._loop, channel).start(
            multiplexer,
            self._end_host,
            self._end_port,
            self._endpoint_connection_error_callback,
        )


class ConnectorHandler(ChannelFlowControlBase):
    """Handle connection to endpoint."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        channel: MultiplexerChannel,
    ) -> None:
        """Initialize ConnectorHandler."""
        super().__init__(loop)
        self._channel = channel

    async def start(
        self,
        multiplexer: Multiplexer,
        end_host: str,
        end_port: int,
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
