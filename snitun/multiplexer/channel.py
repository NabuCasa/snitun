"""Multiplexer channel."""
import asyncio
import logging
from ipaddress import IPv4Address
import uuid

import async_timeout

from ..utils.ipaddress import ip_address_to_bytes
from ..exceptions import MultiplexerTransportClose, MultiplexerTransportError
from .message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA, CHANNEL_FLOW_NEW,
                      MultiplexerMessage)

_LOGGER = logging.getLogger(__name__)


class MultiplexerChannel:
    """Represent a multiplexer channel."""

    def __init__(self,
                 output: asyncio.Queue,
                 ip_address: IPv4Address,
                 channel_id=None) -> None:
        """Initialize Multiplexer Channel."""
        self._input = asyncio.Queue(5)
        self._output = output
        self._id = channel_id or uuid.uuid4()
        self._ip_address = ip_address

    @property
    def uuid(self) -> uuid.UUID:
        """Return UUID of this channel."""
        return self._id

    @property
    def ip_address(self):
        """Return caller IP4Address."""
        return self._ip_address

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

    async def read(self) -> MultiplexerMessage:
        """Read data from peer."""
        message = await self._input.get()

        if message.flow_type == CHANNEL_FLOW_DATA:
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
        extra = b"4" + ip_address_to_bytes(self.ip_address)
        return MultiplexerMessage(self._id, CHANNEL_FLOW_NEW, b"", extra)

    async def message_transport(self, message: MultiplexerMessage) -> None:
        """Only for internal ussage of core transport."""
        if self._input.full():
            _LOGGER.warning("Channel %s input is full", self._id)
            return

        await self._input.put(message)
