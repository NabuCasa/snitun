"""Test Multiplexer channels."""

import asyncio
import os

import pytest

from snitun.multiplexer.message import (
    CHANNEL_FLOW_DATA,
    HEADER_SIZE,
    MultiplexerChannelId,
    MultiplexerMessage,
)
from snitun.multiplexer.queue import (
    MultiplexerMultiChannelQueue,
    MultiplexerSingleChannelQueue,
)

MOCK_MSG_SIZE: int = 4


def _make_mock_channel_id() -> MultiplexerChannelId:
    return MultiplexerChannelId(os.urandom(16))


def _make_mock_message(
    channel_id: MultiplexerChannelId,
    size: int = MOCK_MSG_SIZE,
) -> MultiplexerMessage:
    return MultiplexerMessage(channel_id, CHANNEL_FLOW_DATA, b"x" * size)


async def test_single_channel_queue() -> None:
    """Test MultiplexerSingleChannelQueue.

    Note that the queue is allowed to go over by one message
    because we are subclassing asyncio.Queue and it is not
    possible to prevent this without reimplementing the whole
    class, which is not worth it since its ok if we go over by
    one message.
    """
    queue = MultiplexerSingleChannelQueue()
    channel_id = _make_mock_channel_id()
    msg = _make_mock_message(channel_id)
    assert queue.qsize() == 0
    queue.put_nowait(msg)
    assert queue.qsize() == len(msg.data) + HEADER_SIZE
    assert queue.get_nowait() == msg
    assert queue.qsize() == 0
    queue.put_nowait(None)
    assert queue.qsize() == 0


async def test_multi_channel_queue_full() -> None:
    """Test MultiplexerMultiChannelQueue getting full."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    queue = MultiplexerMultiChannelQueue(
        msg_size * 2,
    )  # Max two mock messages per channel
    channel_one_id = _make_mock_channel_id()
    channel_two_id = _make_mock_channel_id()

    channel_one_msg = _make_mock_message(channel_one_id)
    channel_two_msg = _make_mock_message(channel_two_id)

    queue.put_nowait(channel_one_id, channel_one_msg)
    queue.put_nowait(channel_one_id, channel_one_msg)
    with pytest.raises(asyncio.QueueFull):
        queue.put_nowait(channel_one_id, channel_one_msg)
    queue.put_nowait(channel_two_id, channel_two_msg)
    queue.put_nowait(channel_two_id, channel_two_msg)
    with pytest.raises(asyncio.QueueFull):
        queue.put_nowait(channel_two_id, channel_two_msg)

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            await queue.put(channel_one_id, channel_one_msg)

    assert queue.get_nowait() == channel_one_msg

    add_task = asyncio.create_task(queue.put(channel_one_id, channel_one_msg))
    await asyncio.sleep(0)
    assert not add_task.done()
    assert queue.get_nowait() == channel_two_msg
    await asyncio.sleep(0)
    assert not add_task.done()
    assert queue.get_nowait() == channel_one_msg
    await asyncio.sleep(0)
    assert add_task.done()
    await add_task


async def test_multi_channel_queue_round_robin_get() -> None:
    """Test MultiplexerMultiChannelQueue round robin get."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    queue = MultiplexerMultiChannelQueue(
        msg_size * 2,
    )  # Max two mock messages per channel
    channel_one_id = _make_mock_channel_id()
    channel_two_id = _make_mock_channel_id()
    channel_three_id = _make_mock_channel_id()

    channel_one_msg = _make_mock_message(channel_one_id)
    assert queue.empty(channel_one_id)
    await queue.put(channel_one_id, channel_one_msg)
    assert not queue.empty(channel_one_id)
    assert queue.size(channel_one_id) == len(channel_one_msg.data) + HEADER_SIZE

    channel_two_msg = _make_mock_message(channel_two_id)
    assert queue.empty(channel_two_id)
    await queue.put(channel_two_id, channel_two_msg)
    assert not queue.empty(channel_two_id)
    assert queue.size(channel_two_id) == len(channel_two_msg.data) + HEADER_SIZE

    channel_three_msg = _make_mock_message(channel_three_id)
    assert queue.empty(channel_three_id)
    queue.put_nowait(channel_three_id, channel_three_msg)
    assert not queue.empty(channel_three_id)
    assert queue.size(channel_three_id) == len(channel_three_msg.data) + HEADER_SIZE

    assert queue.get_nowait() == channel_one_msg
    assert queue.empty(channel_one_id)
    assert queue.size(channel_one_id) == 0

    assert queue.get_nowait() == channel_two_msg
    assert queue.empty(channel_two_id)
    assert queue.size(channel_two_id) == 0

    assert queue.get_nowait() == channel_three_msg
    assert queue.empty(channel_three_id)
    assert queue.size(channel_three_id) == 0

    with pytest.raises(asyncio.QueueEmpty):
        queue.get_nowait()

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            await queue.get()

    queue.put_nowait(channel_two_id, channel_two_msg)
    queue.put_nowait(channel_three_id, channel_three_msg)
    queue.put_nowait(channel_one_id, channel_one_msg)
    queue.put_nowait(channel_one_id, channel_one_msg)
    queue.put_nowait(channel_three_id, channel_three_msg)
    queue.put_nowait(channel_two_id, channel_two_msg)

    msgs = [queue.get_nowait() for _ in range(6)]
    # Queue should be fair regardless of the order of the messages
    # coming in
    assert msgs == [
        channel_two_msg,
        channel_three_msg,
        channel_one_msg,
        channel_two_msg,
        channel_three_msg,
        channel_one_msg,
    ]

    with pytest.raises(asyncio.QueueEmpty):
        queue.get_nowait()


async def test_concurrent_get() -> None:
    """Test MultiplexerMultiChannelQueue concurrent get."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    queue = MultiplexerMultiChannelQueue(
        msg_size * 2,
    )  # Max two mock messages per channel
    channel_one_id = _make_mock_channel_id()
    channel_two_id = _make_mock_channel_id()
    channel_three_id = _make_mock_channel_id()
    channel_one_msg = _make_mock_message(channel_one_id)
    channel_two_msg = _make_mock_message(channel_two_id)
    channel_three_msg = _make_mock_message(channel_three_id)

    fetch_tasks = [asyncio.create_task(queue.get()) for _ in range(3)]

    await queue.put(channel_one_id, channel_one_msg)
    await queue.put(channel_two_id, channel_two_msg)
    await queue.put(channel_three_id, channel_three_msg)

    fetched_msgs = await asyncio.gather(*fetch_tasks)

    assert channel_one_msg in fetched_msgs
    assert channel_two_msg in fetched_msgs
    assert channel_three_msg in fetched_msgs

    with pytest.raises(asyncio.QueueEmpty):
        queue.get_nowait()
