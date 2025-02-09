"""Multiplexer for SniTun."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from contextlib import suppress
import ipaddress
import logging
import os
import sys
from typing import Any

from ..exceptions import (
    MultiplexerTransportClose,
    MultiplexerTransportDecrypt,
    MultiplexerTransportError,
)
from ..utils.asyncio import asyncio_timeout, make_task_waiter_future
from ..utils.ipaddress import bytes_to_ip_address
from .channel import MultiplexerChannel
from .crypto import CryptoTransport
from .message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    CHANNEL_FLOW_PING,
    MultiplexerChannelId,
    MultiplexerMessage,
)

_LOGGER = logging.getLogger(__name__)

PEER_TCP_TIMEOUT = 90


class Multiplexer:
    """Multiplexer Socket wrapper."""

    __slots__ = [
        "_channels",
        "_crypto",
        "_healthy",
        "_loop",
        "_new_connections",
        "_queue",
        "_read_task",
        "_reader",
        "_throttling",
        "_write_task",
        "_writer",
    ]

    def __init__(
        self,
        crypto: CryptoTransport,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        new_connections: Coroutine[Any, Any, None] | None = None,
        throttling: int | None = None,
    ) -> None:
        """Initialize Multiplexer."""
        self._crypto = crypto
        self._reader = reader
        self._writer = writer
        self._loop = asyncio.get_event_loop()
        self._queue = asyncio.Queue(12000)
        self._healthy = asyncio.Event()
        self._healthy.set()
        self._read_task = self._loop.create_task(self._read_from_peer_loop())
        self._write_task = self._loop.create_task(self._write_to_peer_loop())
        self._channels: dict[MultiplexerChannelId, MultiplexerChannel] = {}
        self._new_connections = new_connections
        self._throttling = 1 / throttling if throttling else None

    @property
    def is_connected(self) -> bool:
        """Return True is they is connected."""
        return not self._write_task.done()

    def wait(self) -> asyncio.Future[None]:
        """Block until the connection is closed.

        Return a awaitable object.
        """
        return make_task_waiter_future(self._write_task)

    def shutdown(self) -> None:
        """Shutdown connection."""
        if self._write_task.done():
            return

        _LOGGER.debug("Cancel connection")
        self._write_task.cancel()
        self._graceful_channel_shutdown()

    def _graceful_channel_shutdown(self) -> None:
        """Graceful shutdown of channels."""
        for channel in self._channels.values():
            channel.close()
        self._channels.clear()

    async def ping(self) -> None:
        """Send a ping flow message to hold the connection open."""
        self._healthy.clear()
        try:
            self._write_message(
                MultiplexerMessage(
                    MultiplexerChannelId(),
                    CHANNEL_FLOW_PING,
                    b"",
                    b"ping",
                ),
            )

            # Wait until pong is received
            async with asyncio_timeout.timeout(PEER_TCP_TIMEOUT):
                await self._healthy.wait()

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout error while pinging peer")
            self._loop.call_soon(self.shutdown)
            raise MultiplexerTransportError from None

        except OSError as exception:
            _LOGGER.error("Peer ping failed - %s", exception)
            self._loop.call_soon(self.shutdown)
            raise MultiplexerTransportError from None

    async def _read_from_peer_loop(self) -> None:
        """Read from peer loop."""
        transport = self._writer.transport
        try:
            while not transport.is_closing():
                async with asyncio_timeout.timeout(PEER_TCP_TIMEOUT):
                    from_peer = await self._reader.readexactly(32)
                await self._read_message(from_peer)
                if self._throttling:
                    await asyncio.sleep(self._throttling)
        except asyncio.CancelledError:
            _LOGGER.debug("Receive canceling")
            raise
        except (
            MultiplexerTransportClose,
            asyncio.IncompleteReadError,
            OSError,
        ):
            _LOGGER.debug("Transport was closed")
        finally:
            self._write_task.cancel()

    async def _write_to_peer_loop(self) -> None:
        """Write to peer loop."""
        transport = self._writer.transport
        try:
            while not transport.is_closing():
                async with asyncio_timeout.timeout(PEER_TCP_TIMEOUT):
                    to_peer = await self._queue.get()
                self._write_message(to_peer)
                await self._writer.drain()
        except asyncio.CancelledError:
            _LOGGER.debug("Write canceling")
            with suppress(OSError):
                self._writer.write_eof()
            if (
                sys.version_info >= (3, 11)
                and (current_task := asyncio.current_task())
                and current_task.cancelling()
            ):
                raise
        except (asyncio.TimeoutError, TimeoutError):
            _LOGGER.debug("Receive canceling")
            with suppress(OSError):
                self._writer.write_eof()
                await self._writer.drain()
        except (MultiplexerTransportClose, OSError):
            _LOGGER.debug("Transport was closed")
        finally:
            self._read_task.cancel()
            # Cleanup transport
            if not self._writer.transport.is_closing():
                with suppress(OSError):
                    self._writer.close()
            self._graceful_channel_shutdown()
            _LOGGER.debug("Multiplexer connection is closed")

    def _write_message(self, message: MultiplexerMessage) -> None:
        """Write message to peer."""
        header = message.id.bytes
        header += message.flow_type.to_bytes(1, byteorder="big")
        header += len(message.data).to_bytes(4, byteorder="big")
        header += message.extra + os.urandom(11 - len(message.extra))

        data = self._crypto.encrypt(header) + message.data
        try:
            self._writer.write(data)
        except RuntimeError:
            raise MultiplexerTransportClose from None

    async def _read_message(self, header: bytes) -> None:
        """Read message from peer."""
        if not header:
            raise MultiplexerTransportClose

        try:
            header = self._crypto.decrypt(header)
            channel_id = header[:16]
            flow_type = header[16]
            data_size = int.from_bytes(header[17:21], byteorder="big")
            extra = header[21:]
        except (IndexError, MultiplexerTransportDecrypt):
            _LOGGER.warning("Wrong message header received")
            return

        # Read message data
        if data_size:
            data = await self._reader.readexactly(data_size)
        else:
            data = b""

        message = MultiplexerMessage(
            MultiplexerChannelId(channel_id),
            flow_type,
            data,
            extra,
        )

        # Process message to queue
        await self._process_message(message)

    async def _process_message(self, message: MultiplexerMessage) -> None:
        """Process received message."""
        # DATA
        if message.flow_type == CHANNEL_FLOW_DATA:
            # check if message exists
            if message.id not in self._channels:
                _LOGGER.debug("Receive data from unknown channel")
                return

            channel = self._channels[message.id]
            if channel.closing:
                pass
            elif channel.healthy:
                _LOGGER.warning("Abort connection, channel is not healthy")
                channel.close()
                self._loop.create_task(self.delete_channel(channel))
            else:
                channel.message_transport(message)

        # New
        elif message.flow_type == CHANNEL_FLOW_NEW:
            # Check if we would handle new connection
            if not self._new_connections:
                _LOGGER.warning("Request new Channel is not allow")
                return

            ip_address = bytes_to_ip_address(message.extra[1:5])
            channel = MultiplexerChannel(
                self._queue,
                ip_address,
                channel_id=message.id,
                throttling=self._throttling,
            )
            self._channels[channel.id] = channel
            self._loop.create_task(self._new_connections(self, channel))

        # Close
        elif message.flow_type == CHANNEL_FLOW_CLOSE:
            # check if message exists
            if message.id not in self._channels:
                _LOGGER.debug("Receive close from unknown channel")
                return
            channel = self._channels.pop(message.id)
            channel.close()

        # Ping
        elif message.flow_type == CHANNEL_FLOW_PING:
            if message.extra.startswith(b"pong"):
                _LOGGER.debug("Receive pong from peer / reset healthy")
                self._healthy.set()
            else:
                _LOGGER.debug("Receive ping from peer / send pong")
                self._write_message(
                    MultiplexerMessage(message.id, CHANNEL_FLOW_PING, b"", b"pong"),
                )

        else:
            _LOGGER.warning("Receive unknown message type")

    async def create_channel(
        self,
        ip_address: ipaddress.IPv4Address,
    ) -> MultiplexerChannel:
        """Create a new channel for transport."""
        channel = MultiplexerChannel(
            self._queue,
            ip_address,
            throttling=self._throttling,
        )
        message = channel.init_new()

        try:
            async with asyncio_timeout.timeout(5):
                await self._queue.put(message)
        except asyncio.TimeoutError:
            raise MultiplexerTransportError from None

        self._channels[channel.id] = channel

        return channel

    async def delete_channel(self, channel: MultiplexerChannel) -> None:
        """Delete channel from transport."""
        message = channel.init_close()

        try:
            async with asyncio_timeout.timeout(5):
                await self._queue.put(message)
        except asyncio.TimeoutError:
            raise MultiplexerTransportError from None
        finally:
            self._channels.pop(channel.id, None)
