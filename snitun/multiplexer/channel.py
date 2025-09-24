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
    INCOMING_QUEUE_MAX_BYTES_CHANNEL_V0,
)
from .message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    CHANNEL_FLOW_PAUSE,
    CHANNEL_FLOW_RESUME,
    MIN_PROTOCOL_VERSION_FOR_PAUSE_RESUME,
    MultiplexerChannelId,
    MultiplexerMessage,
)
from .queue import MultiplexerMultiChannelQueue, MultiplexerSingleChannelQueue

_LOGGER = logging.getLogger(__name__)


class ChannelFlowControlBase:
    """A channel that implements flow control."""

    _channel: MultiplexerChannel

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        """Initialize a channel that implements flow control."""
        self._loop = loop
        self._pause_future: asyncio.Future[None] | None = None
        self._debug = _LOGGER.isEnabledFor(logging.DEBUG)

    def _pause_resume_reader_callback(self, pause: bool) -> None:
        """Pause and resume reader."""
        channel = self._channel
        ip_address = channel.ip_address
        id_ = channel.id
        if not pause:
            if self._pause_future and not self._pause_future.done():
                if self._debug:
                    _LOGGER.debug("Resuming reader for %s (%s)", ip_address, id_)
                self._pause_future.set_result(None)
                self._pause_future = None
                return
            # Already resumed - this is idempotent, no error needed
            if self._debug:
                _LOGGER.debug(
                    "Reader already resumed for %s (%s), ignoring",
                    ip_address,
                    id_,
                )
            return

        if self._pause_future is None or self._pause_future.done():
            if self._debug:
                _LOGGER.debug("Pause reader for %s (%s)", ip_address, id_)
            self._pause_future = self._loop.create_future()
            return

        # Already paused - this is idempotent, no error needed
        if self._debug:
            _LOGGER.debug(
                "Reader already paused for %s (%s), ignoring",
                ip_address,
                id_,
            )


class MultiplexerChannel:
    """Represent a multiplexer channel."""

    __slots__ = (
        "_closing",
        "_debug",
        "_id",
        "_input",
        "_ip_address",
        "_local_output_under_water",
        "_output",
        "_pause_resume_reader_callback",
        "_peer_protocol_version",
        "_reader_paused",
        "_remote_input_under_water",
        "_throttling",
    )

    def __init__(
        self,
        output: MultiplexerMultiChannelQueue,
        ip_address: IPv4Address,
        peer_protocol_version: int,
        pause_resume_reader_callback: Callable[[bool], None] | None = None,
        channel_id: MultiplexerChannelId | None = None,
        throttling: float | None = None,
    ) -> None:
        """Initialize Multiplexer Channel."""
        if peer_protocol_version == 0:
            # For protocol version 0, we use a larger queue since
            # we can't tell the client to pause/resume reading.
            # This is a temporary solution until we can remove protocol version 0.
            incoming_queue_max_bytes_channel = INCOMING_QUEUE_MAX_BYTES_CHANNEL_V0
        else:
            incoming_queue_max_bytes_channel = INCOMING_QUEUE_MAX_BYTES_CHANNEL
        self._input = MultiplexerSingleChannelQueue(
            incoming_queue_max_bytes_channel,
            INCOMING_QUEUE_LOW_WATERMARK,
            INCOMING_QUEUE_HIGH_WATERMARK,
            self._on_local_input_under_water,
        )
        self._output = output
        self._id = channel_id or MultiplexerChannelId(os.urandom(16))
        self._ip_address = ip_address
        self._peer_protocol_version = peer_protocol_version
        self._throttling = throttling
        self._closing = False
        # Backpressure - We track when our output queue is under water
        # or the remote input queue is under water so we can pause reading
        # of whatever is connected to this channel to prevent overflowing
        # either queue.
        self._local_output_under_water = False
        self._remote_input_under_water = False
        self._output.create_channel(self._id, self._on_local_output_under_water)
        self._pause_resume_reader_callback = pause_resume_reader_callback
        self._reader_paused = False
        self._debug = _LOGGER.isEnabledFor(logging.DEBUG)

    def set_pause_resume_reader_callback(
        self,
        pause_resume_reader_callback: Callable[[bool], None],
    ) -> None:
        """Set pause resume reader callback."""
        self._pause_resume_reader_callback = pause_resume_reader_callback

    def _on_local_input_under_water(self, under_water: bool) -> None:
        """On callback from the input queue when goes under water or recovers."""
        if self._peer_protocol_version < MIN_PROTOCOL_VERSION_FOR_PAUSE_RESUME:
            if self._debug:
                _LOGGER.debug(
                    "Remote does not support pause/resume, ignoring %s input water",
                    self._id,
                )
            return
        msg_type = CHANNEL_FLOW_PAUSE if under_water else CHANNEL_FLOW_RESUME
        # Tell the remote that our input queue is under water so it
        # can pause reading from whatever is connected to this channel
        if self._debug:
            _LOGGER.debug(
                "Informing remote that %s input is now %s water",
                self._id,
                "under" if under_water else "above",
            )
        try:
            self._output.put_nowait(self._id, MultiplexerMessage(self._id, msg_type))
        except asyncio.QueueFull:
            _LOGGER.warning(
                "%s: Cannot send pause/resume message to peer, output queue is full",
                self._id,
            )

    def _on_local_output_under_water(self, under_water: bool) -> None:
        """On callback from the output queue when goes under water or recovers."""
        if self._debug:
            _LOGGER.debug(
                "Local output is under water: %s for %s",
                under_water,
                self._id,
            )
        self._local_output_under_water = under_water
        self._pause_or_resume_reader()

    def on_remote_input_under_water(self, under_water: bool) -> None:
        """Call when remote input is under water."""
        if self._debug:
            _LOGGER.debug(
                "Remote input is under water: %s for %s",
                under_water,
                self._id,
            )
        self._remote_input_under_water = under_water
        self._pause_or_resume_reader()

    def _pause_or_resume_reader(self) -> None:
        """Pause or resume reader."""
        # Pause if either local output or remote input is under water
        # Resume if both local output and remote input are not under water
        if self._pause_resume_reader_callback is None:
            return
        pause_reader = self._local_output_under_water or self._remote_input_under_water
        if self._reader_paused != pause_reader:
            # Call the callback first, then update state if successful
            # This ensures state consistency even if callback fails
            self._pause_resume_reader_callback(pause_reader)
            self._reader_paused = pause_reader

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
        _LOGGER.debug("Schedule close channel %s", self._id)
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
            # Try to avoid the timer handle if we can
            # add to the queue without waiting
            self._output.put_nowait(self._id, message)
        except asyncio.QueueFull:
            try:
                async with asyncio_timeout.timeout(5):
                    await self._output.put(self._id, message)
            except TimeoutError:
                if self._debug:
                    _LOGGER.debug("Can't write to peer transport")
                raise MultiplexerTransportError from None

        if self._throttling is not None:
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
        if self._debug:
            _LOGGER.debug("Sending close channel %s", self._id)
        return MultiplexerMessage(self._id, CHANNEL_FLOW_CLOSE)

    def init_new(self) -> MultiplexerMessage:
        """Init new session for transport."""
        if self._debug:
            _LOGGER.debug("Sending new channel %s", self._id)
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
