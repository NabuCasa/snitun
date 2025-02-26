"""Tests for asyncio utils."""

import asyncio

import pytest

from snitun.utils.asyncio import (
    asyncio_timeout,
    create_eager_task,
    make_task_waiter_future,
    RangedTimeout
)


async def test_asyncio_timeout() -> None:
    """Init aiohttp client for test."""
    with pytest.raises(asyncio.TimeoutError):
        async with asyncio_timeout.timeout(0.1):
            task = asyncio.create_task(asyncio.sleep(10))
            await task

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_create_eager_task() -> None:
    """Test create eager task."""
    task = create_eager_task(asyncio.sleep(0.01))
    await task
    assert task.done()
    assert not task.cancelled()
    assert task.result() is None


async def test_make_task_waiter_future_running_task() -> None:
    """Test make task waiter future for a running task."""
    task = asyncio.create_task(asyncio.sleep(0.01))
    future = make_task_waiter_future(task)
    assert not future.done()
    assert not future.cancelled()
    assert await future is None


async def test_make_task_waiter_future_cancelled_task() -> None:
    """Test make task waiter future when the task is cancelled."""
    task = asyncio.create_task(asyncio.sleep(0.01))
    future = make_task_waiter_future(task)
    task.cancel()
    assert not future.done()
    assert not future.cancelled()
    assert await future is None


async def test_make_task_waiter_future_exception_task() -> None:
    """Test make task waiter future when the task raises."""

    async def _raise_exception() -> None:
        await asyncio.sleep(0)
        raise ValueError("test")

    task = asyncio.create_task(_raise_exception())
    future = make_task_waiter_future(task)
    assert not future.done()
    assert not future.cancelled()
    assert await future is None


async def test_make_task_waiter_future_already_done_task() -> None:
    """Test make task waiter future when the task is already done."""
    task = asyncio.create_task(asyncio.sleep(0))
    await task
    future = make_task_waiter_future(task)
    assert future.done()
    assert not future.cancelled()
    assert future.result() is None


async def test_ranged_timeout() -> None:
    """Test ranged timeout."""
    timed_out: list[bool] = []
    def _timeout_callback() -> None:
        timed_out.append(True)

    ranged = RangedTimeout(0.1, 0.2, _timeout_callback)
    assert timed_out == []
    await asyncio.sleep(0.2)
    assert timed_out == [True]
    ranged.cancel()

    timed_out = []
    ranged = RangedTimeout(0.1, 0.2, _timeout_callback)
    await asyncio.sleep(0.1)
    assert timed_out == []
    ranged.cancel()

    timed_out = []
    ranged = RangedTimeout(0.1, 0.2, _timeout_callback)
    await asyncio.sleep(0.15)
    assert timed_out == []
    ranged.reschedule()
    await asyncio.sleep(0.2)
    assert timed_out == [True]
    ranged.cancel()
    await asyncio.sleep(0.1)
    assert timed_out == [True]
