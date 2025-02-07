"""Tests for asyncio utils."""

import asyncio
from snitun.utils.asyncio import asyncio_timeout, create_eager_task
import pytest

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
