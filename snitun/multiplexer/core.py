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
from ..utils.asyncio import (
    RangedTimeout,
    asyncio_timeout,
    create_eager_task,
    make_task_waiter_future,
)
from ..utils.ipaddress import bytes_to_ip_address
from .channel import MultiplexerChannel
from .const import (
    OUTGOING_QUEUE_HIGH_WATERMARK,
    OUTGOING_QUEUE_LOW_WATERMARK,
    OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
)
from .crypto import CryptoTransport
from .message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    CHANNEL_FLOW_PAUSE,
    CHANNEL_FLOW_PING,
    CHANNEL_FLOW_RESUME,
    HEADER_SIZE,
    HEADER_STRUCT,
    MultiplexerChannelId,
    MultiplexerMessage,
)
from .queue import MultiplexerMultiChannelQueue

_LOGGER = logging.getLogger(__name__)

PEER_TCP_MIN_TIMEOUT = 90
PEER_TCP_MAX_TIMEOUT = 120
MIN_SIZE_THROTTLE = 8192


class Multiplexer:
    """Multiplexer Socket wrapper."""

    __slots__ = [
        "_channel_tasks",
        "_channels",
        "_crypto",
        "_healthy",
        "_loop",
        "_new_connections",
        "_peer_protocol_version",
        "_processing_task",
        "_queue",
        "_ranged_timeout",
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
        peer_protocol_version: int,
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
        self._peer_protocol_version = peer_protocol_version
        self._loop = asyncio.get_event_loop()
        self._queue = MultiplexerMultiChannelQueue(
            OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
            OUTGOING_QUEUE_LOW_WATERMARK,
            OUTGOING_QUEUE_HIGH_WATERMARK,
        )
        self._healthy = asyncio.Event()
        self._healthy.set()
        self._read_task = create_eager_task(
            self._read_from_peer_loop(),
            loop=self._loop,
        )
        self._write_task = create_eager_task(
            self._write_to_peer_loop(),
            loop=self._loop,
        )
        self._ranged_timeout = RangedTimeout(
            PEER_TCP_MIN_TIMEOUT,
            PEER_TCP_MAX_TIMEOUT,
            self._on_timeout,
        )
        self._channel_tasks: set[asyncio.Task[None]] = set()
        self._channels: dict[MultiplexerChannelId, MultiplexerChannel] = {}
        self._new_connections = new_connections
        self._throttling = 1 / throttling if throttling else None

    @property
    def is_connected(self) -> bool:
        """Return True is they is connected."""
        return not self._write_task.done()

    def _on_timeout(self) -> None:
        """Handle timeout."""
        _LOGGER.error("Timed out reading and writing to peer")
        self._write_task.cancel()

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
            self._queue.delete_channel(channel.id)
            channel.close()
        self._channels.clear()

    async def ping(self) -> None:
        """Send a ping flow message to hold the connection open."""
        self._healthy.clear()
        channel_id = MultiplexerChannelId(os.urandom(16))
        try:
            self._write_message(
                MultiplexerMessage(channel_id, CHANNEL_FLOW_PING, b"", b"ping"),
            )

            # Wait until pong is received
            async with asyncio_timeout.timeout(PEER_TCP_MIN_TIMEOUT):
                await self._healthy.wait()

        except TimeoutError:
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
                await self._read_message()
                self._ranged_timeout.reschedule()
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
                data_len = 0
                if to_peer := await self._queue.get():
                    data_len = self._write_message(to_peer)
                await self._writer.drain()
                self._ranged_timeout.reschedule()
                if to_peer is not None and self._throttling is not None:
                    # Throttle the connection to ensure
                    # we have enough time to get back
                    # pause messages to not overrun the
                    # remote input queue. If the message
                    # is large > 64KB we use self._throttling
                    # for the sleep value, otherwise for small
                    # messages we use 0 as to still yield to the
                    # event loop but not have to schedule the
                    # task again since the overhead of the task
                    # scheduling creates a significant CPU overhead.
                    to_sleep = 0 if data_len < MIN_SIZE_THROTTLE else self._throttling
                    await asyncio.sleep(to_sleep)
        except asyncio.CancelledError:
            _LOGGER.debug("Write canceling")
            with suppress(OSError):
                self._writer.write_eof()
                await self._writer.drain()
            # Don't swallow cancellation
            if (current_task := asyncio.current_task()) and current_task.cancelling():
                raise
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

    def _write_message(self, message: MultiplexerMessage) -> int:
        """Write message to peer."""
        id_, flow_type, data, extra = message
        data_len = len(data)
        header = HEADER_STRUCT.pack(
            id_.bytes,
            flow_type,
            data_len,
            extra + os.urandom(11 - len(extra)),
        )
        try:
            encrypted_header = self._crypto.encrypt(header)
            payload = encrypted_header + data if data_len else encrypted_header
            self._writer.write(payload)
        except RuntimeError:
            raise MultiplexerTransportClose from None
        return data_len

    async def _read_message(self) -> None:
        """Read message from peer."""
        header = await self._reader.readexactly(HEADER_SIZE)

        channel_id: bytes
        flow_type: int
        data_size: int
        extra: bytes
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
            (MultiplexerChannelId(channel_id), flow_type, data, extra),
        )

        # Process message to queue
        # DATA
        flow_type = message.flow_type
        if flow_type == CHANNEL_FLOW_DATA:
            # check if message exists
            if message.id not in self._channels:
                _LOGGER.debug("Receive data from unknown channel: %s", message.id)
                return

            channel = self._channels[message.id]
            if channel.closing:
                pass
            elif channel.unhealthy:
                _LOGGER.warning(
                    "Abort connection, channel %s is not healthy",
                    channel.id,
                )
                channel.close()
                self.delete_channel(channel)
            else:
                channel.message_transport(message)

        # New
        elif flow_type == CHANNEL_FLOW_NEW:
            # Check if we would handle new connection
            if not self._new_connections:
                _LOGGER.warning("Request new Channel is not allow")
                return

            ip_address = bytes_to_ip_address(message.extra[1:5])
            channel = MultiplexerChannel(
                self._queue,
                ip_address,
                self._peer_protocol_version,
                channel_id=message.id,
                throttling=self._throttling,
            )
            self._channels[channel.id] = channel
            self._create_channel_task(self._new_connections(self, channel))

        # Close
        elif flow_type == CHANNEL_FLOW_CLOSE:
            # check if message exists
            if channel_ := self._delete_channel_and_queue(message.id):
                channel_.close()
            else:
                _LOGGER.debug("Receive close from unknown channel: %s", message.id)

        # Ping
        elif flow_type == CHANNEL_FLOW_PING:
            if message.extra.startswith(b"pong"):
                _LOGGER.debug("Receive pong from peer / reset healthy")
                self._healthy.set()
            else:
                _LOGGER.debug("Receive ping from peer / send pong")
                self._write_message(
                    MultiplexerMessage(message.id, CHANNEL_FLOW_PING, b"", b"pong"),
                )

        # Pause or Resume
        elif flow_type in (CHANNEL_FLOW_PAUSE, CHANNEL_FLOW_RESUME):
            # When the remote input is under water state changes
            # call the on_remote_input_under_water method
            if channel_ := self._channels.get(message.id):
                channel_.on_remote_input_under_water(
                    message.flow_type == CHANNEL_FLOW_PAUSE,
                )
            else:
                _LOGGER.debug(
                    "Receive %s from unknown channel: %s",
                    "pause" if flow_type == CHANNEL_FLOW_PAUSE else "resume",
                    message.id,
                )

        else:
            _LOGGER.warning(
                "Receive unknown message type: %s for channel %s",
                message.flow_type,
                message.id,
            )

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
            self._peer_protocol_version,
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

    def delete_channel(self, channel: MultiplexerChannel) -> None:
        """Delete channel from transport."""
        if channel.id not in self._channels:
            # Make sure the queue is cleaned up if the channel
            # is already deleted
            self._queue.delete_channel(channel.id)
            return

        message = channel.init_close()
        try:
            self._queue.put_nowait_force(channel.id, message)
        finally:
            self._delete_channel_and_queue(channel.id)

    def _delete_channel_and_queue(
        self,
        channel_id: MultiplexerChannelId,
    ) -> MultiplexerChannel | None:
        """Delete channel and queue from multiplexer if it exists."""
        self._queue.delete_channel(channel_id)
        return self._channels.pop(channel_id, None)
