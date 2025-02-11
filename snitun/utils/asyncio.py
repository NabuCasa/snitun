"""Utils for asyncio."""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")

asyncio_timeout = asyncio


def create_eager_task(
    coro: Coroutine[Any, Any, _T],
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


def make_task_waiter_future(task: asyncio.Task) -> asyncio.Future[None]:
    """Create a future that waits for a task to complete.

    A future is used to ensure that cancellation of the
    task does not propagate to the waiter.
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[None] = loop.create_future()

    def _resolve_future(_: asyncio.Task) -> None:
        if not fut.done():
            fut.set_result(None)

    if task.done():
        _resolve_future(task)
        return fut

    task.add_done_callback(_resolve_future)
    return fut
