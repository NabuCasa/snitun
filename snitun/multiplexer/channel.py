"""Multiplexer channel."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from ipaddress import IPv4Address
import logging
import os

from ..exceptions import MultiplexerTransportClose, MultiplexerTransportError
from ..utils.asyncio import asyncio_timeout
from ..utils.ipaddress import ip_address_to_bytes
from .const import (
    INCOMING_QUEUE_HIGH_WATERMARK,
    INCOMING_QUEUE_LOW_WATERMARK,
    INCOMING_QUEUE_MAX_BYTES_CHANNEL,
)
from .message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    CHANNEL_FLOW_PAUSE,
    CHANNEL_FLOW_RESUME,
    MultiplexerChannelId,
    MultiplexerMessage,
)
from .queue import MultiplexerMultiChannelQueue, MultiplexerSingleChannelQueue

_LOGGER = logging.getLogger(__name__)


class MultiplexerChannel:
    """Represent a multiplexer channel."""

    __slots__ = (
        "_closing",
        "_id",
        "_input",
        "_ip_address",
        "_local_output_under_water",
        "_output",
        "_pause_resume_reader_callback",
        "_remote_input_under_water",
        "_throttling",
    )

    def __init__(
        self,
        output: MultiplexerMultiChannelQueue,
        ip_address: IPv4Address,
        pause_resume_reader_callback: Callable[[bool], None] | None = None,
        channel_id: MultiplexerChannelId | None = None,
        throttling: float | None = None,
    ) -> None:
        """Initialize Multiplexer Channel."""
        self._input = MultiplexerSingleChannelQueue(
            INCOMING_QUEUE_MAX_BYTES_CHANNEL,
            INCOMING_QUEUE_LOW_WATERMARK,
            INCOMING_QUEUE_HIGH_WATERMARK,
            self._local_input_under_water_callback,
        )
        self._output = output
        self._id = channel_id or MultiplexerChannelId(os.urandom(16))
        self._ip_address = ip_address
        self._throttling = throttling
        self._closing = False
        # Backpressure
        self._local_output_under_water = False
        self._remote_input_under_water = False
        self._output.create_channel(self._id, self._local_output_under_water_callback)
        self._pause_resume_reader_callback = pause_resume_reader_callback

    def set_pause_resume_reader_callback(
        self,
        pause_resume_reader_callback: Callable[[bool], None],
    ) -> None:
        """Set pause resume reader callback."""
        self._pause_resume_reader_callback = pause_resume_reader_callback

    def _local_input_under_water_callback(self, under_water: bool) -> None:
        """Set local input under water."""
        msg_type = CHANNEL_FLOW_PAUSE if under_water else CHANNEL_FLOW_RESUME
        self.message_transport(MultiplexerMessage(self._id, msg_type))

    def _local_output_under_water_callback(self, under_water: bool) -> None:
        """Set local output under water."""
        self._local_output_under_water = under_water
        self._pause_or_resume_reader()

    def remote_input_under_water_callback(self, under_water: bool) -> None:
        """Set remote input under water."""
        self._remote_input_under_water = under_water
        self._pause_or_resume_reader()

    def _pause_or_resume_reader(self) -> None:
        """Pause or resume reader."""
        # Pause if either local output or remote input is under water
        # Resume if both local output and remote input are not under water
        if self._pause_resume_reader_callback is not None:
            self._pause_resume_reader_callback(
                self._local_output_under_water or self._remote_input_under_water,
            )

    @property
    def id(self) -> MultiplexerChannelId:
        """Return ID of this channel."""
        return self._id

    @property
    def ip_address(self) -> IPv4Address:
        """Return caller IP4Address."""
        return self._ip_address

    @property
    def unhealthy(self) -> bool:
        """Return True if an error has occurred."""
        return self._input.full()

    @property
    def closing(self) -> bool:
        """Return True if channel is in closing state."""
        return self._closing

    def close(self) -> None:
        """Close channel on next run."""
        self._closing = True
        with suppress(asyncio.QueueFull):
            self._input.put_nowait(None)

    async def write(self, data: bytes) -> None:
        """Send data to peer."""
        if not data:
            raise MultiplexerTransportError
        if self._closing:
            raise MultiplexerTransportClose

        # Create message
        message = tuple.__new__(
            MultiplexerMessage,
            (self._id, CHANNEL_FLOW_DATA, data, b""),
        )

        try:
            async with asyncio_timeout.timeout(5):
                await self._output.put(self.id, message)
        except TimeoutError:
            _LOGGER.debug("Can't write to peer transport")
            raise MultiplexerTransportError from None

        if not self._throttling:
            return
        await asyncio.sleep(self._throttling)

    async def read(self) -> bytes:
        """Read data from peer."""
        if self._closing and self._input.empty():
            message = None
        else:
            message = await self._input.get()

        # Send data
        if message is not None:
            return message.data

        _LOGGER.debug("Read a close message for channel %s", self._id)
        raise MultiplexerTransportClose

    def init_close(self) -> MultiplexerMessage:
        """Init close message for transport."""
        _LOGGER.debug("Close channel %s", self._id)
        return MultiplexerMessage(self._id, CHANNEL_FLOW_CLOSE)

    def init_new(self) -> MultiplexerMessage:
        """Init new session for transport."""
        _LOGGER.debug("New channel %s", self._id)
        extra = b"4" + ip_address_to_bytes(self.ip_address)
        return MultiplexerMessage(self._id, CHANNEL_FLOW_NEW, b"", extra)

    def message_transport(self, message: MultiplexerMessage) -> None:
        """Only for internal usage of core transport."""
        if self._closing:
            return

        try:
            self._input.put_nowait(message)
        except asyncio.QueueFull:
            _LOGGER.warning("Channel %s input is full", self._id)
