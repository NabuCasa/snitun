"""Utils for asyncio."""

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

_T = TypeVar("_T")

asyncio_timeout = asyncio


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
