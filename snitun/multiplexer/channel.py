"""Multiplexer channel."""
import asyncio
import logging
import uuid

from .message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA, CHANNEL_FLOW_NEW,
                      MultiplexerMessage)

_LOGGER = logging.getLogger(__name__)


class MultiplexerChannel:
    """Represent a multiplexer channel."""

    def __init__(self, output: asyncio.Queue) -> None:
        """Initialize Multiplexer Channel."""
        self._input: asyncio.Queue = asyncio.Queue(5)
        self._output: asyncio.Queue = output
        self._id: str = uuid.uuid4()

    async def new(self) -> None:
        """Initialize a new session on peer."""
        message = MultiplexerMessage(self._id, CHANNEL_FLOW_NEW, b'')
        await self._output.put(message)

    async def write(self, data: bytes) -> None:
        """Send data to peer."""
        message = MultiplexerMessage(self._id, CHANNEL_FLOW_DATA, data)
        await self._output.put(message)

    async def read(self) -> MultiplexerMessage:
        """Read data from peer."""
        message = await self._input.get()

        if message.flow_type == CHANNEL_FLOW_DATA:
            return message.data

        return None

    async def close(self) -> None:
        """Close channel."""
        message = MultiplexerMessage(self._id, CHANNEL_FLOW_CLOSE, b'')
        await self._output.put(message)
