"""Multiplexer for SniTun."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import suppress
import ipaddress
import logging
import os
import struct
from typing import Any

from ..exceptions import (
    MultiplexerTransportClose,
    MultiplexerTransportDecrypt,
    MultiplexerTransportError,
)
from ..utils.asyncio import asyncio_timeout
from ..utils.ipaddress import bytes_to_ip_address
from .channel import MultiplexerChannel
from .const import (
    OUTGOING_QUEUE_HIGH_WATERMARK,
    OUTGOING_QUEUE_LOW_WATERMARK,
    OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
    PEER_TCP_TIMEOUT,
)
from .crypto import CryptoTransport
from .message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    CHANNEL_FLOW_PAUSE,
    CHANNEL_FLOW_PING,
    CHANNEL_FLOW_RESUME,
    HEADER_STRUCT,
    MultiplexerChannelId,
    MultiplexerMessage,
)
from .queue import MultiplexerMultiChannelQueue

_LOGGER = logging.getLogger(__name__)


class Multiplexer:
    """Multiplexer Socket wrapper."""

    __slots__ = [
        "_channel_tasks",
        "_channels",
        "_crypto",
        "_healthy",
        "_loop",
        "_new_connections",
        "_processing_task",
        "_queue",
        "_reader",
        "_throttling",
        "_writer",
    ]

    def __init__(
        self,
        crypto: CryptoTransport,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        new_connections: Callable[
            [Multiplexer, MultiplexerChannel],
            Coroutine[Any, Any, None],
        ]
        | None = None,
        throttling: int | None = None,
    ) -> None:
        """Initialize Multiplexer."""
        self._crypto = crypto
        self._reader = reader
        self._writer = writer
        self._loop = asyncio.get_event_loop()
        self._queue = MultiplexerMultiChannelQueue(
            OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
            OUTGOING_QUEUE_LOW_WATERMARK,
            OUTGOING_QUEUE_HIGH_WATERMARK,
        )
        self._healthy = asyncio.Event()
        self._channel_tasks: set[asyncio.Task[None]] = set()
        self._processing_task = self._loop.create_task(self._runner())
        self._channels: dict[MultiplexerChannelId, MultiplexerChannel] = {}
        self._new_connections = new_connections
        self._throttling = 1 / throttling if throttling else None

    @property
    def is_connected(self) -> bool:
        """Return True is they is connected."""
        return not self._processing_task.done()

    def wait(self) -> asyncio.Future[None]:
        """Block until the connection is closed.

        Return a awaitable object.
        """
        return asyncio.shield(self._processing_task)

    def shutdown(self) -> None:
        """Shutdown connection."""
        if self._processing_task.done():
            return

        _LOGGER.debug("Cancel connection")
        self._processing_task.cancel()
        self._graceful_channel_shutdown()

    def _graceful_channel_shutdown(self) -> None:
        """Graceful shutdown of channels."""
        for channel in self._channels.values():
            self._queue.delete_channel(channel.id)
            channel.close()
        self._channels.clear()

    async def ping(self) -> None:
        """Send a ping flow message to hold the connection open."""
        self._healthy.clear()
        try:
            self._write_message(
                MultiplexerMessage(
                    MultiplexerChannelId(os.urandom(16)),
                    CHANNEL_FLOW_PING,
                    b"",
                    b"ping",
                ),
            )

            # Wait until pong is received
            async with asyncio_timeout.timeout(PEER_TCP_TIMEOUT):
                await self._healthy.wait()

        except TimeoutError:
            _LOGGER.error("Timeout error while pinging peer")
            self._loop.call_soon(self.shutdown)
            raise MultiplexerTransportError from None

        except OSError as exception:
            _LOGGER.error("Peer ping failed - %s", exception)
            self._loop.call_soon(self.shutdown)
            raise MultiplexerTransportError from None

    async def _runner(self) -> None:
        """Runner task of processing stream."""
        transport = self._writer.transport
        from_peer = None
        to_peer = None

        # Process stream
        self._healthy.set()
        try:
            while not transport.is_closing():
                if not from_peer:
                    from_peer = self._loop.create_task(self._reader.readexactly(32))

                if not to_peer:
                    to_peer = self._loop.create_task(self._queue.get())

                # Wait until data need to be processed
                async with asyncio_timeout.timeout(PEER_TCP_TIMEOUT):
                    await asyncio.wait(
                        [from_peer, to_peer],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                # From peer
                if from_peer.done():
                    if from_peer_exc := from_peer.exception():
                        raise from_peer_exc
                    await self._read_message(from_peer.result())
                    from_peer = None

                # To peer
                if to_peer.done():
                    if to_peer_exc := to_peer.exception():
                        raise to_peer_exc
                    if msg := to_peer.result():
                        self._write_message(msg)
                    to_peer = None

                    # Flush buffer
                    await self._writer.drain()

                # throttling
                if not self._throttling:
                    continue
                await asyncio.sleep(self._throttling)

        except (asyncio.CancelledError, TimeoutError):
            _LOGGER.debug("Receive canceling")
            with suppress(OSError):
                self._writer.write_eof()
                await self._writer.drain()

        except (
            MultiplexerTransportClose,
            asyncio.IncompleteReadError,
            ConnectionResetError,
            OSError,
        ):
            _LOGGER.debug("Transport was closed")

        finally:
            # Cleanup peer writer
            if to_peer and not to_peer.done():
                to_peer.cancel()

            # Cleanup peer reader
            if from_peer:
                if not from_peer.done():
                    from_peer.cancel()
                else:
                    # Avoid exception was never retrieved
                    from_peer.exception()

            # Cleanup transport
            if not transport.is_closing():
                with suppress(OSError):
                    self._writer.close()

            self._graceful_channel_shutdown()
            _LOGGER.debug("Multiplexer connection is closed")

    def _write_message(self, message: MultiplexerMessage) -> None:
        """Write message to peer."""
        id_, flow_type, data, extra = message
        header = HEADER_STRUCT.pack(
            id_.bytes,
            flow_type,
            len(data),
            extra + os.urandom(11 - len(extra)),
        )
        try:
            self._writer.write(self._crypto.encrypt(header) + data)
        except RuntimeError:
            raise MultiplexerTransportClose from None

    async def _read_message(self, header: bytes) -> None:
        """Read message from peer."""
        if not header:
            raise MultiplexerTransportClose

        try:
            channel_id, flow_type, data_size, extra = HEADER_STRUCT.unpack(
                self._crypto.decrypt(header),
            )
        except (struct.error, MultiplexerTransportDecrypt):
            _LOGGER.warning("Wrong message header received")
            return

        # Read message data
        if data_size:
            data = await self._reader.readexactly(data_size)
        else:
            data = b""

        message = tuple.__new__(
            MultiplexerMessage,
            (
                MultiplexerChannelId(channel_id),
                flow_type,
                data,
                extra,
            ),
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
            elif channel.unhealthy:
                _LOGGER.warning("Abort connection, channel is not healthy")
                channel.close()
                self._create_channel_task(self.delete_channel(channel))
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
            self._create_channel_task(self._new_connections(self, channel))

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

        # Pause or Resume
        elif message.flow_type in (CHANNEL_FLOW_PAUSE, CHANNEL_FLOW_RESUME):
            # When the remote input is under water state changes
            # call the on_remote_input_under_water method
            under_water = message.flow_type == CHANNEL_FLOW_PAUSE
            if channel_ := self._channels.get(message.id):
                channel_.on_remote_input_under_water(under_water)

        else:
            _LOGGER.warning("Receive unknown message type")

    def _create_channel_task(self, coro: Coroutine[Any, Any, None]) -> None:
        """Create a new task for channel."""
        task = self._loop.create_task(coro)
        self._channel_tasks.add(task)
        task.add_done_callback(self._channel_tasks.remove)

    async def create_channel(
        self,
        ip_address: ipaddress.IPv4Address,
        pause_resume_reader_callback: Callable[[bool], None],
    ) -> MultiplexerChannel:
        """Create a new channel for transport."""
        channel = MultiplexerChannel(
            self._queue,
            ip_address,
            pause_resume_reader_callback,
            throttling=self._throttling,
        )
        message = channel.init_new()

        try:
            async with asyncio_timeout.timeout(5):
                await self._queue.put(channel.id, message)
        except TimeoutError:
            raise MultiplexerTransportError from None

        self._channels[channel.id] = channel

        return channel

    async def delete_channel(self, channel: MultiplexerChannel) -> None:
        """Delete channel from transport."""
        message = channel.init_close()

        try:
            async with asyncio_timeout.timeout(5):
                await self._queue.put(channel.id, message)
        except TimeoutError:
            raise MultiplexerTransportError from None
        finally:
            self._channels.pop(channel.id, None)
            self._queue.delete_channel(channel.id)
