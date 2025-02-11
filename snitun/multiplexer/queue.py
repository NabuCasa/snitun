"""Multiplexer message queues."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict, deque
import contextlib
from dataclasses import dataclass, field

from .message import HEADER_SIZE, MultiplexerChannelId, MultiplexerMessage


@dataclass(slots=True)
class _ChannelQueue:
    """Channel queue."""

    total_bytes: int = 0
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

    def _put(self, message: MultiplexerMessage | None) -> None:
        """Put a message in the queue."""
        self._total_bytes += _effective_size(message)
        super()._put(message)

    def _get(self) -> MultiplexerMessage | None:
        """Get a message from the queue."""
        message = super()._get()
        self._total_bytes -= _effective_size(message)
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

    def __init__(self, channel_size_limit: int) -> None:
        """Initialize Multiplexer Queue.

        Args:
            channel_size_limit (int): The maximum size of a channel
            data queue in bytes.

        """
        self._channel_size_limit = channel_size_limit
        self._channels: defaultdict[MultiplexerChannelId, _ChannelQueue] = defaultdict(
            _ChannelQueue,
        )
        # order controls which channel_id to get next
        self._order: OrderedDict[MultiplexerChannelId, None] = OrderedDict()
        self._getters: deque[asyncio.Future[None]] = deque()
        self._loop = asyncio.get_running_loop()

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
        channel = self._channels[channel_id]
        size = _effective_size(message)
        while channel.total_bytes + size > self._channel_size_limit:  # full
            putter = self._loop.create_future()
            channel.putters.append(putter)
            try:
                await putter
            except:
                # channel may have been deleted while we were waiting
                # so make sure we look it up again
                channel = self._channels[channel_id]
                putter.cancel()  # Just in case putter is not done yet.
                with contextlib.suppress(ValueError):
                    # Clean self._putters from canceled putters.
                    channel.putters.remove(putter)
                if not self.full(channel_id) and not putter.cancelled():
                    # We were woken up by get_nowait(), but can't take
                    # the call.  Wake up the next in line.
                    self._wakeup_next(channel.putters)
                raise
            else:
                # channel may have been deleted while we were waiting
                # so make sure we look it up again
                channel = self._channels[channel_id]
        self._put(channel_id, channel, message, size)

    def put_nowait(
        self,
        channel_id: MultiplexerChannelId,
        message: MultiplexerMessage | None,
    ) -> None:
        """Put a message in the queue."""
        size = _effective_size(message)
        channel = self._channels[channel_id]
        if channel.total_bytes + size > self._channel_size_limit:
            raise asyncio.QueueFull
        self._put(channel_id, channel, message, size)

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
        self._wakeup_next(self._getters)

    async def get(self) -> MultiplexerMessage | None:
        """
        Asynchronously retrieve a `MultiplexerMessage` from the queue.

        Returns:
            MultiplexerMessage: The message retrieved from the queue.

        """
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
                    # the call.  Wake up the next in line.
                    self._wakeup_next(self._getters)
                raise
        return self.get_nowait()

    def get_nowait(self) -> MultiplexerMessage | None:
        """Get a message from the queue."""
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
        else:
            # Got to the end of the queue
            # As soon as we get to the end of the queue, we will
            # drop the internal deque(), this may result in some churn.
            del self._channels[channel_id]
        if channel.putters:
            self._wakeup_next(channel.putters)
        return message

    def empty(self, channel_id: MultiplexerChannelId) -> bool:
        """Empty the queue."""
        return self._channels[channel_id].total_bytes == 0

    def size(self, channel_id: MultiplexerChannelId) -> int:
        """Return the size of the channel queue in bytes."""
        return self._channels[channel_id].total_bytes

    def full(self, channel_id: MultiplexerChannelId) -> bool:
        """Return True if the channel queue is full."""
        return self._channels[channel_id].total_bytes >= self._channel_size_limit
