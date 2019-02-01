"""Multiplexer for SniTun."""
import asyncio
import logging
import os
import uuid
from contextlib import suppress

import async_timeout

from ..exceptions import (MultiplexerTransportClose,
                          MultiplexerTransportDecrypt,
                          MultiplexerTransportError)
from .channel import MultiplexerChannel
from .crypto import CryptoTransport
from .message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA, CHANNEL_FLOW_NEW,
                      CHANNEL_FLOW_PING, MultiplexerMessage)

_LOGGER = logging.getLogger(__name__)


class Multiplexer:
    """Multiplexer Socket wrapper."""

    def __init__(self,
                 crypto: CryptoTransport,
                 reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter,
                 new_connections=None):
        """Initialize Multiplexer."""
        self._crypto = crypto
        self._reader = reader
        self._writer = writer
        self._loop = asyncio.get_event_loop()
        self._queue = asyncio.Queue(10)
        self._processing_task = self._loop.create_task(self._runner())
        self._channels = {}  # type: Dict[MultiplexerMessage]
        self._new_connections = new_connections

    @property
    def is_connected(self) -> bool:
        """Return True is they is connected."""
        return not self._processing_task.done()

    async def shutdown(self):
        """Shutdown connection."""
        if self._processing_task.done():
            return

        _LOGGER.debug("Cancel connection")
        self._processing_task.cancel()

        await self._graceful_channel_shutdown()

    async def _graceful_channel_shutdown(self):
        """Graceful shutdown of channels."""
        tasks = [
            channel.message_transport(channel.init_close())
            for channel in self._channels.values()
        ]
        self._channels.clear()

        if tasks:
            await asyncio.wait(tasks)

    def wait(self):
        """Block until the connection is closed.

        Return a awaitable object.
        """
        return self._processing_task

    def ping(self):
        """Send a ping flow message to hold the connection open."""
        message = MultiplexerMessage(uuid.uuid4(), CHANNEL_FLOW_PING)
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
                    from_peer = self._loop.create_task(
                        self._reader.readexactly(32))

                if not to_peer:
                    to_peer = self._loop.create_task(self._queue.get())

                # Wait until data need to be processed
                await asyncio.wait([from_peer, to_peer],
                                   return_when=asyncio.FIRST_COMPLETED)

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

        except asyncio.CancelledError:
            _LOGGER.debug("Receive canceling")
            with suppress(OSError):
                self._writer.write_eof()
                await self._writer.drain()

        except (MultiplexerTransportClose, asyncio.IncompleteReadError):
            _LOGGER.debug("Transport was closed")

        finally:
            if to_peer and not to_peer.done():
                to_peer.cancel()
            if from_peer and not from_peer.done():
                from_peer.cancel()
            if not transport.is_closing():
                with suppress(OSError):
                    self._writer.close()

        await self._graceful_channel_shutdown()
        _LOGGER.debug("Multiplexer connection is closed")

    def _write_message(self, message: MultiplexerMessage) -> None:
        """Write message to peer."""
        header = message.channel_id.bytes
        header += message.flow_type.to_bytes(1, byteorder='big')
        header += len(message.data).to_bytes(4, byteorder='big')
        header += os.urandom(11)

        data = self._crypto.encrypt(header) + message.data
        self._writer.write(data)

    async def _read_message(self, header: bytes) -> None:
        """Read message from peer."""
        if not header:
            raise MultiplexerTransportClose()

        try:
            header = self._crypto.decrypt(header)
            channel_id = header[:16]
            flow_type = header[16]
            data_size = int.from_bytes(header[17:21], byteorder='big')
        except (IndexError, MultiplexerTransportDecrypt):
            _LOGGER.waring("Wrong message header received")
            return

        # Read message data
        if data_size:
            data = await self._reader.readexactly(data_size)
        else:
            data = b""

        message = MultiplexerMessage(
            uuid.UUID(bytes=channel_id), flow_type, data)

        # Process message to queue
        await self._process_message(message)

    async def _process_message(self, message: MultiplexerMessage) -> None:
        """Process received message."""

        # DATA
        if message.flow_type == CHANNEL_FLOW_DATA:
            # check if message exists
            if message.channel_id not in self._channels:
                _LOGGER.waring("Receive data from unknown channel")
                return
            await self._channels[message.channel_id].message_transport(message)

        # New
        if message.flow_type == CHANNEL_FLOW_NEW:
            # Check if we would handle new connection
            if not self._new_connections:
                _LOGGER.warning("Request new Channel is not allow")
                return

            channel = MultiplexerChannel(self._queue, message.channel_id)
            self._channels[channel.uuid] = channel
            self._loop.create_task(self._new_connections(channel))

        # Close
        if message.flow_type == CHANNEL_FLOW_CLOSE:
            # check if message exists
            if message.channel_id not in self._channels:
                _LOGGER.waring("Receive close from unknown channel")
                return
            channel = self._channels.pop(message.channel_id)
            await channel.message_transport(message)

    async def create_channel(self) -> MultiplexerChannel:
        """Create a new channel for transport."""
        channel = MultiplexerChannel(self._queue)
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
