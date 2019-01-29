"""Multiplexer channel."""
import asyncio
import logging
import uuid

from ..exceptions import MultiplexerTransportError
from .message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA, CHANNEL_FLOW_NEW,
                      MultiplexerMessage)

_LOGGER = logging.getLogger(__name__)


class MultiplexerChannel:
    """Represent a multiplexer channel."""

    def __init__(self, output: asyncio.Queue) -> None:
        """Initialize Multiplexer Channel."""
        self._input: asyncio.Queue = asyncio.Queue(2)
        self._output: asyncio.Queue = output
        self._id: uuid.UUID = uuid.uuid4()

    @property
    def id(self) -> uuid.UUID:
        """Return UUID of this channel."""
        return self._id

    @property
    def input_queue(self) -> asyncio.Queue:
        """Return input queue for this channel."""
        return self._input

    async def new(self) -> None:
        """Initialize a new session on peer."""
        if self._output.full():
            raise MultiplexerTransportError()

        message = MultiplexerMessage(self._id, CHANNEL_FLOW_NEW)
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
        if self._output.full():
            raise MultiplexerTransportError()

        message = MultiplexerMessage(self._id, CHANNEL_FLOW_CLOSE)
        await self._output.put(message)
