"""Multiplexer for SniTun."""
import asyncio
from contextlib import suppress
import ipaddress
import logging
import os
from typing import Optional
import uuid

import async_timeout

from ..exceptions import (
    MultiplexerTransportClose,
    MultiplexerTransportDecrypt,
    MultiplexerTransportError,
)
from ..utils.ipaddress import bytes_to_ip_address
from .channel import MultiplexerChannel
from .crypto import CryptoTransport
from .message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    CHANNEL_FLOW_PING,
    MultiplexerMessage,
)

_LOGGER = logging.getLogger(__name__)


class Multiplexer:
    """Multiplexer Socket wrapper."""

    def __init__(
        self,
        crypto: CryptoTransport,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        new_connections=None,
        throttling: Optional[int] = None,
    ):
        """Initialize Multiplexer."""
        self._crypto = crypto
        self._reader = reader
        self._writer = writer
        self._loop = asyncio.get_event_loop()
        self._queue = asyncio.Queue(30)
        self._processing_task = self._loop.create_task(self._runner())
        self._channels = {}
        self._new_connections = new_connections
        self._throttling = 1 / throttling if throttling else None

    @property
    def is_connected(self) -> bool:
        """Return True is they is connected."""
        return not self._processing_task.done()

    def wait(self) -> asyncio.Task:
        """Block until the connection is closed.

        Return a awaitable object.
        """
        return asyncio.shield(self._processing_task)

    async def shutdown(self):
        """Shutdown connection."""
        if self._processing_task.done():
            return

        _LOGGER.debug("Cancel connection")
        self._processing_task.cancel()

        self._graceful_channel_shutdown()

    def _graceful_channel_shutdown(self):
        """Graceful shutdown of channels."""
        for channel in self._channels.values():
            channel.close()
        self._channels.clear()

    def ping(self):
        """Send a ping flow message to hold the connection open."""
        message = MultiplexerMessage(uuid.uuid4(), CHANNEL_FLOW_PING)
        with supress(asyncio.QueueFull):
            self._queue.put_nowait(message)

    async def _runner(self):
        """Runner task of processing stream."""
        transport = self._writer.transport
        from_peer = None
        to_peer = None

        # Process stream
        try:
            while not transport.is_closing():
                if not from_peer:
                    from_peer = self._loop.create_task(self._reader.readexactly(32))

                if not to_peer:
                    to_peer = self._loop.create_task(self._queue.get())

                # Wait until data need to be processed
                await asyncio.wait(
                    [from_peer, to_peer], return_when=asyncio.FIRST_COMPLETED
                )

                # From peer
                if from_peer.done():
                    if from_peer.exception():
                        raise from_peer.exception()
                    await self._read_message(from_peer.result())
                    from_peer = None

                # To peer
                if to_peer.done():
                    if to_peer.exception():
                        raise to_peer.exception()
                    self._write_message(to_peer.result())
                    to_peer = None

                # throttling
                if not self._throttling:
                    continue
                await asyncio.sleep(self._throttling)

        except asyncio.CancelledError:
            _LOGGER.debug("Receive canceling")
            with suppress(OSError):
                self._writer.write_eof()
                await self._writer.drain()

        except (MultiplexerTransportClose, asyncio.IncompleteReadError, OSError):
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
        header = message.channel_id.bytes
        header += message.flow_type.to_bytes(1, byteorder="big")
        header += len(message.data).to_bytes(4, byteorder="big")
        header += message.extra + os.urandom(11 - len(message.extra))

        data = self._crypto.encrypt(header) + message.data
        try:
            self._writer.write(data)
        except RuntimeError:
            raise MultiplexerTransportClose() from None

    async def _read_message(self, header: bytes) -> None:
        """Read message from peer."""
        if not header:
            raise MultiplexerTransportClose()

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
            uuid.UUID(bytes=channel_id), flow_type, data, extra
        )

        # Process message to queue
        await self._process_message(message)

    async def _process_message(self, message: MultiplexerMessage) -> None:
        """Process received message."""

        # DATA
        if message.flow_type == CHANNEL_FLOW_DATA:
            # check if message exists
            if message.channel_id not in self._channels:
                _LOGGER.debug("Receive data from unknown channel")
                return

            channel = self._channels[message.channel_id]
            if channel.closing:
                pass
            elif channel.error:
                _LOGGER.warning("Abort connection, error on channel detected")
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
            channel = MultiplexerChannel(self._queue, ip_address, message.channel_id)
            self._channels[channel.uuid] = channel
            self._loop.create_task(self._new_connections(self, channel))

        # Close
        elif message.flow_type == CHANNEL_FLOW_CLOSE:
            # check if message exists
            if message.channel_id not in self._channels:
                _LOGGER.debug("Receive close from unknown channel")
                return
            channel = self._channels.pop(message.channel_id)
            channel.close()

        # Ping
        elif message.flow_type == CHANNEL_FLOW_PING:
            _LOGGER.debug("Receive ping from peer")

        else:
            _LOGGER.warning("Receive unknown message. Abort connection")
            self._loop.create_task(self.shutdown())

    async def create_channel(
        self, ip_address: ipaddress.IPv4Address
    ) -> MultiplexerChannel:
        """Create a new channel for transport."""
        channel = MultiplexerChannel(self._queue, ip_address)
        message = channel.init_new()

        try:
            async with async_timeout.timeout(5):
                await self._queue.put(message)
        except asyncio.TimeoutError:
            raise MultiplexerTransportError() from None
        else:
            self._channels[channel.uuid] = channel

        return channel

    async def delete_channel(self, channel: MultiplexerChannel) -> None:
        """Delete channel from transport."""
        message = channel.init_close()

        try:
            async with async_timeout.timeout(5):
                await self._queue.put(message)
        except asyncio.TimeoutError:
            raise MultiplexerTransportError() from None
        finally:
            self._channels.pop(channel.uuid, None)
