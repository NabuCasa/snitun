"""Utils for asyncio."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

_T = TypeVar("_T")

asyncio_timeout = asyncio


class RangedTimeout:
    """Ranged Timeout.

    RangedTimeout is a class that allows
    to set a minimum and maximum timeout.

    The timeout callback will be called
    at some time between the minimum and
    maximum timeout.

    This is a low resolution timeout that
    avoids the overhead of creating a new
    timer for each timeout if the timeout
    is changed frequently.
    """

    __slots__ = (
        "_loop",
        "_max_timeout",
        "_min_timeout",
        "_timeout_callback",
        "_timer",
        "_when",
    )

    def __init__(
        self,
        min_timeout: float,
        max_timeout: float,
        timeout_callback: Callable[[], None],
    ) -> None:
        """Initialize RangedTimeout."""
        self._min_timeout = min_timeout
        self._max_timeout = max_timeout
        self._timeout_callback = timeout_callback
        self._when: float | None = None
        self._timer: asyncio.TimerHandle | None = None
        self._loop = asyncio.get_running_loop()
        self.reschedule()

    def reschedule(self) -> None:
        """Reschedule the timeout."""
        now = self._loop.time()
        remaining = self._when - now if self._when else 0
        if remaining > self._min_timeout:
            return
        self._when = now + self._max_timeout
        self.cancel()
        self._timer = self._loop.call_at(self._when, self._timeout_callback)

    def cancel(self) -> None:
        """Cancel the timeout."""
        if self._timer:
            self._timer.cancel()
            self._timer = None


make_task_waiter_future = asyncio.shield


def create_eager_task(
    coro: Awaitable[_T],
    *,
    name: str | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> asyncio.Task[_T]:
    """Create a task from a coroutine and schedule it to run immediately."""
    return asyncio.Task(
        coro,
        loop=loop or asyncio.get_running_loop(),
        name=name,
        eager_start=True,  # type: ignore[call-arg]
    )
