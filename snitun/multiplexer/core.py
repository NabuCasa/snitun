"""Multiplexer for SniTun."""
import asyncio
import logging
import uuid

import async_timeout

from ..exceptions import MultiplexerTransportClose, MultiplexerTransportError
from .message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA, CHANNEL_FLOW_NEW,
                      CHANNEL_FLOW_PING, MultiplexerMessage)
from .channel import MultiplexerChannel

_LOGGER = logging.getLogger(__name__)


class Multiplexer:
    """Multiplexer Socket wrapper."""

    def __init__(self,
                 reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter,
                 new_connections=None):
        """Initialize Multiplexer."""
        self._reader = reader
        self._writer = writer
        self._loop = asyncio.get_event_loop()
        self._queue = asyncio.Queue(10)
        self._processing_task = self._loop.create_task(self._runner())
        self._channels = {}  # type: Dict[MultiplexerMessage]
        self._new_connections = new_connections

    async def shutdown(self):
        """Shutdown connection."""
        if self._processing_task.done():
            return

        _LOGGER.debug("Cancel connection")
        self._processing_task.cancel()

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
                    from_peer = self._loop.create_task(self._reader.read(21))

                if not to_peer:
                    to_peer = self._loop.create_task(self._queue.get())

                # Wait until data need to be processed
                await asyncio.wait([from_peer, to_peer],
                                   return_when=asyncio.FIRST_COMPLETED)

                # To peer
                if to_peer.done():
                    self._write_message(to_peer.result())
                    to_peer = None

                # From peer
                if from_peer.done():
                    await self._read_message(from_peer.result())
                    from_peer = None

        except asyncio.CancelledError:
            _LOGGER.debug("Receive canceling")
            self._writer.write_eof()
            await self._writer.drain()

        except MultiplexerTransportClose:
            _LOGGER.debug("Transport was closed")

        finally:
            if to_peer and not to_peer.done():
                to_peer.cancel()
            if from_peer and not from_peer.done():
                from_peer.cancel()
            if not transport.is_closing():
                self._writer.close()

        _LOGGER.debug("Multiplexer connection is closed")

    def _write_message(self, message: MultiplexerMessage) -> None:
        """Write message to peer."""
        data = message.channel_id.bytes
        data += message.flow_type.to_bytes(1, byteorder='big')
        data += len(message.data).to_bytes(4, byteorder='big')
        data += message.data

        self._writer.write(data)

    async def _read_message(self, header: bytes) -> None:
        """Read message from peer."""
        if not header:
            raise MultiplexerTransportClose()

        try:
            channel_id = header[0:15]
            flow_type = int.from_bytes(header[16], byteorder='big')
            data_size = int.from_bytes(header[17:21], byteorder='big')
        except IndexError:
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

            channel = MultiplexerChannel(self._queue)
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
            self._channels[channel.uuid] = channel
        finally:
            self._channels.pop(channel, None)
