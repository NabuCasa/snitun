"""Multiplexer message handling."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict, deque
import contextlib

from .message import MultiplexerChannelId, MultiplexerMessage


class MultiplexerQueue:
    """Multiplexer queue."""

    def __init__(self, channel_size_limit: int) -> None:
        """Initialize Multiplexer Queue.

        Args:
            channel_size_limit (int): The maximum size of a channel
            data queue in bytes.

        """
        self._channel_size_limit = channel_size_limit
        self._buckets: defaultdict[
            MultiplexerChannelId,
            deque[MultiplexerMessage | None],
        ] = defaultdict(deque)
        self._bucket_sizes: defaultdict[MultiplexerChannelId, int] = defaultdict(int)
        # order controls which channel_id to get next
        self._order: OrderedDict[MultiplexerChannelId, None] = OrderedDict()
        self._total_messages = 0
        self._getters: deque[asyncio.Future[None]] = deque()
        self._putters: defaultdict[
            MultiplexerChannelId,
            deque[asyncio.Future[None]],
        ] = defaultdict(deque)
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
        while self.full(channel_id):
            putter = self._loop.create_future()
            self._putters[channel_id].append(putter)
            try:
                await putter
            except:
                putter.cancel()  # Just in case putter is not done yet.
                with contextlib.suppress(ValueError):
                    # Clean self._putters from canceled putters.
                    self._putters[channel_id].remove(putter)
                if not self.full(channel_id) and not putter.cancelled():
                    # We were woken up by get_nowait(), but can't take
                    # the call.  Wake up the next in line.
                    self._wakeup_next(self._putters[channel_id])
                raise
        self.put_nowait(channel_id, message)

    def put_nowait(
        self,
        channel_id: MultiplexerChannelId,
        message: MultiplexerMessage | None,
    ) -> None:
        """Put a message in the queue."""
        size = 0 if message is None else len(message.data)
        if self._bucket_sizes[channel_id] >= self._channel_size_limit:
            raise asyncio.QueueFull
        self._buckets[channel_id].append(message)
        self._bucket_sizes[channel_id] += size
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
        message = self._buckets[channel_id].popleft()
        size = 0 if message is None else len(message.data)
        self._bucket_sizes[channel_id] -= size
        if self._buckets[channel_id]:
            # Now put the channel_id back, but at the end of the queue
            # so the next get will get the next waiting channel_id.
            self._order[channel_id] = None
        else:
            # Got to the end of the queue
            del self._buckets[channel_id]
            del self._bucket_sizes[channel_id]
        if putters := self._putters[channel_id]:
            self._wakeup_next(putters)
        return message

    async def empty(self, channel_id: MultiplexerChannelId) -> bool:
        """Empty the queue."""
        return self._bucket_sizes[channel_id] == 0

    def size(self, channel_id: MultiplexerChannelId) -> int:
        """Return the size of the channel queue in bytes."""
        return self._bucket_sizes[channel_id]

    def full(self, channel_id: MultiplexerChannelId) -> bool:
        """Return True if the channel queue is full."""
        return self._bucket_sizes[channel_id] >= self._channel_size_limit
