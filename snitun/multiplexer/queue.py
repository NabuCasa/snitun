"""Multiplexer message queues."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
import logging

from .message import HEADER_SIZE, MultiplexerChannelId, MultiplexerMessage

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _ChannelQueue:
    """Channel queue.

    A queue that manages a single channel, with a size limit.

    total_bytes: the size of the queue in bytes instead of the number of items.
    queue: a deque of MultiplexerMessage | None.
    putters: a deque of asyncio.Future[None] which is used to wake up putters
    when the queue is full and space becomes available.
    """

    under_water_callback: Callable[[bool], None]
    total_bytes: int = 0
    under_water: bool = False
    pending_close: bool = False
    queue: deque[MultiplexerMessage | None] = field(default_factory=deque)
    putters: deque[asyncio.Future[None]] = field(default_factory=deque)


def _effective_size(message: MultiplexerMessage | None) -> int:
    """Return the effective size of the message."""
    return 0 if message is None else HEADER_SIZE + len(message.data)


class MultiplexerSingleChannelQueue(asyncio.Queue[MultiplexerMessage | None]):
    """Multiplexer single channel queue.

    qsize is the size of the queue in bytes instead of the number of items.

    Note that the queue is allowed to go over by one message
    because we are subclassing asyncio.Queue and it is not
    possible to prevent this without reimplementing the whole
    class, which is not worth it since its ok if we go over by
    one message.
    """

    _total_bytes: int = 0

    def __init__(
        self,
        maxsize: int,
        low_water_mark: int,
        high_water_mark: int,
        under_water_callback: Callable[[bool], None],
    ) -> None:
        """Initialize Multiplexer Queue."""
        self._low_water_mark = low_water_mark
        self._high_water_mark = high_water_mark
        self._under_water_callback = under_water_callback
        self._under_water: bool = False
        super().__init__(maxsize)

    def _put(self, message: MultiplexerMessage | None) -> None:
        """Put a message in the queue."""
        self._total_bytes += _effective_size(message)
        super()._put(message)
        if not self._under_water and self._total_bytes >= self._high_water_mark:
            self._under_water = True
            self._under_water_callback(True)

    def _get(self) -> MultiplexerMessage | None:
        """Get a message from the queue."""
        message = super()._get()
        self._total_bytes -= _effective_size(message)
        if self._under_water and self._total_bytes <= self._low_water_mark:
            self._under_water = False
            self._under_water_callback(False)
        return message

    def qsize(self) -> int:
        """Size of the queue in bytes."""
        return self._total_bytes


class MultiplexerMultiChannelQueue:
    """Multiplexer multi channel queue.

    A queue that manages multiple channels, each with a size limit.
    This class allows for asynchronous message passing between multiple channels,
    ensuring that each channel does not exceed a specified size limit.

    When fetching from the queue, the channels are fetched in a round-robin
    fashion, ensuring that no channel is starved.
    """

    def __init__(
        self,
        channel_size_limit: int,
        channel_low_water_mark: int,
        channel_high_water_mark: int,
    ) -> None:
        """Initialize Multiplexer Queue.

        Args:
            channel_size_limit (int): The maximum size of a channel
            data queue in bytes.

        """
        self._channel_size_limit = channel_size_limit
        self._channel_low_water_mark = channel_low_water_mark
        self._channel_high_water_mark = channel_high_water_mark
        self._channels: dict[MultiplexerChannelId, _ChannelQueue] = {}
        # _order controls which channel_id to get next. We use
        # an OrderedDict because we need to use popitem(last=False)
        # here to maintain FIFO order.
        self._order: OrderedDict[MultiplexerChannelId, None] = OrderedDict()
        self._getters: deque[asyncio.Future[None]] = deque()
        self._loop = asyncio.get_running_loop()

    def create_channel(
        self,
        channel_id: MultiplexerChannelId,
        under_water_callback: Callable[[bool], None],
    ) -> None:
        """Create a new channel."""
        _LOGGER.debug("Queue creating channel %s", channel_id)
        if channel_id in self._channels:
            raise RuntimeError(f"Channel {channel_id} already exists")
        self._channels[channel_id] = _ChannelQueue(under_water_callback)

    def delete_channel(self, channel_id: MultiplexerChannelId) -> None:
        """Delete a channel."""
        if channel := self._channels.get(channel_id):
            if channel.queue:
                channel.pending_close = True
            else:
                del self._channels[channel_id]

    def _wakeup_next(self, waiters: deque[asyncio.Future[None]]) -> None:
        """Wake up the next waiter."""
        while waiters:
            waiter = waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                break

    async def put(
        self,
        channel_id: MultiplexerChannelId,
        message: MultiplexerMessage | None,
    ) -> None:
        """Put a message in the queue."""
        # Based on asyncio.Queue.put()
        if not (channel := self._channels.get(channel_id)):
            raise RuntimeError(f"Channel {channel_id} does not exist or already closed")
        size = _effective_size(message)
        while channel.total_bytes + size > self._channel_size_limit:  # full
            putter = self._loop.create_future()
            channel.putters.append(putter)
            try:
                await putter
            except:
                putter.cancel()  # Just in case putter is not done yet.
                with contextlib.suppress(ValueError):
                    # Clean self._putters from canceled putters.
                    channel.putters.remove(putter)
                if not self.full(channel_id) and not putter.cancelled():
                    # We were woken up by get_nowait(), but can't take
                    # the call. Wake up the next in line.
                    self._wakeup_next(channel.putters)
                raise
        self._put(channel_id, channel, message, size)

    def put_nowait(
        self,
        channel_id: MultiplexerChannelId,
        message: MultiplexerMessage | None,
    ) -> None:
        """Put a message in the queue.

        Raises:
            asyncio.QueueFull: If the queue is full.
        """
        size = _effective_size(message)
        if not (channel := self._channels.get(channel_id)):
            raise RuntimeError(f"Channel {channel_id} does not exist or already closed")
        if channel.total_bytes + size > self._channel_size_limit:
            raise asyncio.QueueFull
        self._put(channel_id, channel, message, size)

    def put_nowait_force(
        self,
        channel_id: MultiplexerChannelId,
        message: MultiplexerMessage | None,
    ) -> None:
        """Put a message in the queue.

        This method is used to force a message into the queue without
        checking if the queue is full. This is used when a channel is
        being closed.
        """
        if not (channel := self._channels.get(channel_id)):
            raise RuntimeError(f"Channel {channel_id} does not exist or already closed")
        self._put(channel_id, channel, message, _effective_size(message))

    def _put(
        self,
        channel_id: MultiplexerChannelId,
        channel: _ChannelQueue,
        message: MultiplexerMessage | None,
        size: int,
    ) -> None:
        """Put a message in the queue."""
        channel.queue.append(message)
        channel.total_bytes += size
        self._order[channel_id] = None
        if (
            not channel.under_water
            and channel.total_bytes >= self._channel_high_water_mark
        ):
            channel.under_water = True
            channel.under_water_callback(True)
        self._wakeup_next(self._getters)

    async def get(self) -> MultiplexerMessage | None:
        """Asynchronously retrieve the next `MultiplexerMessage` from the queue."""
        # Based on asyncio.Queue.get()
        while not self._order:  # order is which channel_id to get next
            getter = self._loop.create_future()
            self._getters.append(getter)
            try:
                await getter
            except:
                getter.cancel()  # Just in case getter is not done yet.
                with contextlib.suppress(ValueError):
                    # Clean self._getters from canceled getters.
                    self._getters.remove(getter)
                # order is which channel_id to get next
                if self._order and not getter.cancelled():
                    # We were woken up by put_nowait(), but can't take
                    # the call. Wake up the next in line.
                    self._wakeup_next(self._getters)
                raise
        return self.get_nowait()

    def get_nowait(self) -> MultiplexerMessage | None:
        """Get a message from the queue.

        Raises:
            asyncio.QueueEmpty: If the queue is empty.
        """
        if not self._order:
            raise asyncio.QueueEmpty
        channel_id, _ = self._order.popitem(last=False)
        channel = self._channels[channel_id]
        message = channel.queue.popleft()
        size = _effective_size(message)
        channel.total_bytes -= size
        if channel.queue:
            # Now put the channel_id back, but at the end of the queue
            # so the next get will get the next waiting channel_id.
            self._order[channel_id] = None
        elif channel.pending_close:
            # Got to the end of the queue and the channel wants
            # to close so we now drop the channel.
            del self._channels[channel_id]
        if channel.under_water and channel.total_bytes <= self._channel_low_water_mark:
            channel.under_water = False
            channel.under_water_callback(False)
        if channel.putters:
            self._wakeup_next(channel.putters)
        return message

    def empty(self, channel_id: MultiplexerChannelId) -> bool:
        """Empty the queue."""
        if not (channel := self._channels.get(channel_id)):
            return True
        return channel.total_bytes == 0

    def size(self, channel_id: MultiplexerChannelId) -> int:
        """Return the size of the channel queue in bytes."""
        if not (channel := self._channels.get(channel_id)):
            return 0
        return channel.total_bytes

    def full(self, channel_id: MultiplexerChannelId) -> bool:
        """Return True if the channel queue is full."""
        if not (channel := self._channels.get(channel_id)):
            return False
        return channel.total_bytes >= self._channel_size_limit
