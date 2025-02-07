"""Utils for asyncio."""

from asyncio import AbstractEventLoop, Task, get_running_loop
from collections.abc import Awaitable
import sys
from typing import TypeVar

_T = TypeVar("_T")

if sys.version_info >= (3, 11):
    pass
else:
    pass


if sys.version_info >= (3, 12, 0):

    def create_eager_task(
        coro: Awaitable[_T],
        *,
        name: str | None = None,
        loop: AbstractEventLoop | None = None,
    ) -> Task[_T]:
        """Create a task from a coroutine and schedule it to run immediately."""
        return Task(
            coro,
            loop=loop or get_running_loop(),
            name=name,
            eager_start=True,  # type: ignore[call-arg]
        )
else:

    def create_eager_task(
        coro: Awaitable[_T],
        *,
        name: str | None = None,
        loop: AbstractEventLoop | None = None,
    ) -> Task[_T]:
        """Create a task from a coroutine and schedule it to run immediately."""
        return Task(
            coro,
            loop=loop or get_running_loop(),
            name=name,
        )
