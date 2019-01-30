"""Multiplexer channel."""
import asyncio
import logging
import uuid

import async_timeout

from ..exceptions import MultiplexerTransportClose, MultiplexerTransportError
from .message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA, CHANNEL_FLOW_NEW,
                      MultiplexerMessage)

_LOGGER = logging.getLogger(__name__)


class MultiplexerChannel:
    """Represent a multiplexer channel."""

    def __init__(self, output: asyncio.Queue, channel_id=None) -> None:
        """Initialize Multiplexer Channel."""
        self._input = asyncio.Queue(2)
        self._output = output
        self._id = channel_id or uuid.uuid4()

    @property
    def uuid(self) -> uuid.UUID:
        """Return UUID of this channel."""
        return self._id

    async def write(self, data: bytes) -> None:
        """Send data to peer."""
        if not data:
            raise MultiplexerTransportError()

        # Create message
        message = MultiplexerMessage(self._id, CHANNEL_FLOW_DATA, data)

        try:
            async with async_timeout.timeout(5):
                await self._output.put(message)
        except asyncio.TimeoutError:
            _LOGGER.debug("Can't write to peer transport")
            raise MultiplexerTransportError() from None

        _LOGGER.debug("Write message to channel %s", self._id)

    async def read(self) -> MultiplexerMessage:
        """Read data from peer."""
        message = await self._input.get()

        if message.flow_type == CHANNEL_FLOW_DATA:
            _LOGGER.debug("Read message to channel %s", self._id)
            return message.data

        _LOGGER.debug("Read a close message for channel %s", self._id)
        raise MultiplexerTransportClose()

    def init_close(self) -> MultiplexerMessage:
        """Init close message for transport."""
        _LOGGER.debug("Close channel %s", self._id)
        return MultiplexerMessage(self._id, CHANNEL_FLOW_CLOSE)

    def init_new(self) -> MultiplexerMessage:
        """Init new session for transport."""
        _LOGGER.debug("New channel %s", self._id)
        return MultiplexerMessage(self._id, CHANNEL_FLOW_NEW)

    async def message_transport(self, message: MultiplexerMessage) -> None:
        """Only for internal ussage of core transport."""
        if self._input.full():
            _LOGGER.warning("Channel %s input is full", self._id)
            return

        await self._input.put(message)
