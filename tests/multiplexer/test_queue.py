"""Test Multiplexer queue."""

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

MOCK_MSG_SIZE = 4


def _make_mock_channel_id() -> MultiplexerChannelId:
    return MultiplexerChannelId(os.urandom(16))


def _make_mock_message(
    channel_id: MultiplexerChannelId,
    size: int = MOCK_MSG_SIZE,
) -> MultiplexerMessage:
    return MultiplexerMessage(channel_id, CHANNEL_FLOW_DATA, os.urandom(size))


async def test_get_non_existent_channels() -> None:
    """Test MultiplexerMultiChannelQueue get on non-existent channel."""
    queue = MultiplexerMultiChannelQueue(100000, 10, 1000)
    assert queue.empty(_make_mock_channel_id())
    assert not queue.full(_make_mock_channel_id())
    assert queue.size(_make_mock_channel_id()) == 0
    # Make sure defaultdict does not leak
    assert not queue._channels


async def test_single_channel_queue() -> None:
    """Test MultiplexerSingleChannelQueue."""
    queue = MultiplexerSingleChannelQueue(100, 10, 50, lambda _: None)
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
    # Max two mock messages per channel
    queue = MultiplexerMultiChannelQueue(msg_size * 2, msg_size, msg_size * 2)

    channel_one_id = _make_mock_channel_id()
    channel_two_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    queue.create_channel(channel_two_id, lambda _: None)

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

    assert queue.size(channel_one_id) == msg_size * 2

    add_task = asyncio.create_task(queue.put(channel_one_id, channel_one_msg))
    await asyncio.sleep(0)
    assert not add_task.done()
    assert queue.get_nowait() == channel_one_msg
    await asyncio.sleep(0)
    assert add_task.done()
    assert queue.get_nowait() == channel_two_msg


async def test_multi_channel_queue_round_robin_get() -> None:
    """Test MultiplexerMultiChannelQueue round robin get."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    # Max two mock messages per channel
    queue = MultiplexerMultiChannelQueue(msg_size * 2, msg_size, msg_size * 2)
    channel_one_id = _make_mock_channel_id()
    channel_two_id = _make_mock_channel_id()
    channel_three_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    queue.create_channel(channel_two_id, lambda _: None)
    queue.create_channel(channel_three_id, lambda _: None)

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
    # Max two mock messages per channel
    queue = MultiplexerMultiChannelQueue(msg_size * 2, msg_size, msg_size * 2)
    channel_one_id = _make_mock_channel_id()
    channel_two_id = _make_mock_channel_id()
    channel_three_id = _make_mock_channel_id()

    queue.create_channel(channel_one_id, lambda _: None)
    queue.create_channel(channel_two_id, lambda _: None)
    queue.create_channel(channel_three_id, lambda _: None)

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


async def test_cancel_one_get() -> None:
    """Test the cancellation of a single `get` operation on multiplexer queue."""
    queue = MultiplexerMultiChannelQueue(100000, 10, 10000)
    reader = asyncio.create_task(queue.get())
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)

    channel_one_msg1 = _make_mock_message(channel_one_id)
    channel_one_msg2 = _make_mock_message(channel_one_id)

    await asyncio.sleep(0)

    queue.put_nowait(channel_one_id, channel_one_msg1)
    queue.put_nowait(channel_one_id, channel_one_msg2)
    reader.cancel()

    with pytest.raises(asyncio.CancelledError):
        await reader

    assert await queue.get() == channel_one_msg1


async def test_reader_cancellation() -> None:
    """
    Test behavior of the MultiplexerMultiChannelQueue when a reader task is cancelled.

     Assertions:
        - The cancelled reader task raises asyncio.CancelledError.
        - The remaining reader tasks retrieve the messages from the queue in any order.
    """
    queue = MultiplexerMultiChannelQueue(100000, 10, 10000)
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    channel_one_msg1 = _make_mock_message(channel_one_id)
    channel_one_msg2 = _make_mock_message(channel_one_id)

    async with asyncio.TaskGroup() as tg:
        reader1 = tg.create_task(queue.get())
        reader2 = tg.create_task(queue.get())
        reader3 = tg.create_task(queue.get())

        await asyncio.sleep(0)

        queue.put_nowait(channel_one_id, channel_one_msg1)
        queue.put_nowait(channel_one_id, channel_one_msg2)
        reader1.cancel()

        with pytest.raises(asyncio.CancelledError):
            await reader1

        await reader3

    # Any order is fine as long as we get both messages
    # since task order is not guaranteed
    assert {reader2.result(), reader3.result()} == {channel_one_msg1, channel_one_msg2}


async def test_put_cancel_race() -> None:
    """Test race between putting messages and cancelling the put operation."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    # Max one message
    queue = MultiplexerMultiChannelQueue(msg_size, msg_size, msg_size)
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)

    channel_one_msg_1 = _make_mock_message(channel_one_id)
    channel_one_msg_2 = _make_mock_message(channel_one_id)
    channel_one_msg_3 = _make_mock_message(channel_one_id)

    queue.put_nowait(channel_one_id, channel_one_msg_1)
    assert queue.get_nowait() == channel_one_msg_1
    assert queue.empty(channel_one_id)

    put_1 = asyncio.create_task(queue.put(channel_one_id, channel_one_msg_1))
    put_2 = asyncio.create_task(queue.put(channel_one_id, channel_one_msg_2))
    put_3 = asyncio.create_task(queue.put(channel_one_id, channel_one_msg_3))

    await asyncio.sleep(0)
    assert put_1.done()
    assert not put_2.done()
    assert not put_3.done()

    put_3.cancel()
    await asyncio.sleep(0)
    assert put_3.done()
    assert queue.get_nowait() == channel_one_msg_1
    await asyncio.sleep(0)
    assert queue.get_nowait() == channel_one_msg_2

    await put_2


async def test_putters_cleaned_up_correctly_on_cancellation() -> None:
    """Test that putters are cleaned up correctly when a put operation is canceled."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    # Max one message
    queue = MultiplexerMultiChannelQueue(msg_size, msg_size, msg_size)
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    channel_one_msg_1 = _make_mock_message(channel_one_id)
    channel_one_msg_2 = _make_mock_message(channel_one_id)

    queue.put_nowait(channel_one_id, channel_one_msg_1)

    put_task = asyncio.create_task(queue.put(channel_one_id, channel_one_msg_2))
    await asyncio.sleep(0)

    # Check that the putter is correctly removed from channel putters
    # the task is canceled.
    assert len(queue._channels[channel_one_id].putters) == 1
    put_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await put_task
    assert len(queue._channels[channel_one_id].putters) == 0


async def test_getters_cleaned_up_correctly_on_cancellation() -> None:
    """Test getters are cleaned up correctly when a get operation is canceled."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    # Max one message
    queue = MultiplexerMultiChannelQueue(msg_size, msg_size, msg_size)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            await queue.get()

    assert len(queue._getters) == 0


async def test_cancelled_when_putter_already_removed() -> None:
    """Test put operation is correctly cancelled when the putter is already removed."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    # Max one message
    queue = MultiplexerMultiChannelQueue(msg_size, msg_size, msg_size)
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    channel_one_msg_1 = _make_mock_message(channel_one_id)

    queue.put_nowait(channel_one_id, channel_one_msg_1)
    put_task = asyncio.create_task(queue.put(channel_one_id, channel_one_msg_1))
    await asyncio.sleep(0)

    queue.get_nowait()
    put_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await put_task


async def test_multiple_getters_waiting_multiple_putters() -> None:
    """Test that multiple getters and putters are correctly handled."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    # Max one message
    queue = MultiplexerMultiChannelQueue(msg_size, msg_size, msg_size)
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    channel_one_msg_1 = _make_mock_message(channel_one_id)
    channel_one_msg_2 = _make_mock_message(channel_one_id)
    t1 = asyncio.create_task(queue.put(channel_one_id, channel_one_msg_1))
    t2 = asyncio.create_task(queue.put(channel_one_id, channel_one_msg_2))
    assert await queue.get() == channel_one_msg_1
    assert await queue.get() == channel_one_msg_2
    await t1
    await t2


async def test_get_cancelled_race() -> None:
    """Test cancelling a get operation while another get operation is in progress."""
    queue = MultiplexerMultiChannelQueue(10000000, 10, 10000)
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    channel_one_msg_1 = _make_mock_message(channel_one_id)

    t1 = asyncio.create_task(queue.get())
    t2 = asyncio.create_task(queue.get())

    await asyncio.sleep(0)
    t1.cancel()
    await asyncio.sleep(0)
    assert t1.done()
    await queue.put(channel_one_id, channel_one_msg_1)
    await asyncio.sleep(0)
    assert await t2 == channel_one_msg_1


async def test_get_with_other_putters() -> None:
    """Test that a get operation is correctly handled when other putters are waiting."""
    loop = asyncio.get_running_loop()
    queue = MultiplexerMultiChannelQueue(10000000, 10, 10000)
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    channel_one_msg_1 = _make_mock_message(channel_one_id)

    queue.put_nowait(channel_one_id, channel_one_msg_1)
    other_putter = loop.create_future()
    queue._channels[channel_one_id].putters.append(other_putter)

    assert await queue.get() == channel_one_msg_1
    assert other_putter.done()
    assert await other_putter is None

    await queue.put(channel_one_id, channel_one_msg_1)
    assert queue.get_nowait() == channel_one_msg_1


async def test_get_with_other_putter_already_one() -> None:
    """Test that a get operation is correctly handled when other putters are waiting."""
    loop = asyncio.get_running_loop()
    queue = MultiplexerMultiChannelQueue(10000000, 10, 10000)
    channel_one_id = _make_mock_channel_id()
    queue.create_channel(channel_one_id, lambda _: None)
    channel_one_msg_1 = _make_mock_message(channel_one_id)

    queue.put_nowait(channel_one_id, channel_one_msg_1)
    other_putter = loop.create_future()
    other_putter.set_result(None)
    queue._channels[channel_one_id].putters.append(other_putter)

    assert await queue.get() == channel_one_msg_1
    assert other_putter.done()
    assert await other_putter is None

    await queue.put(channel_one_id, channel_one_msg_1)
    assert queue.get_nowait() == channel_one_msg_1


async def test_single_channel_queue_under_water() -> None:
    """Test MultiplexerSingleChannelQueue under water."""
    msg_size = MOCK_MSG_SIZE + HEADER_SIZE
    under_water_callbacks: list[bool] = []

    def on_under_water(under_water: bool) -> None:
        under_water_callbacks.append(under_water)

    queue = MultiplexerSingleChannelQueue(
        msg_size * 10,
        msg_size * 2,
        msg_size * 4,
        on_under_water,
    )
    channel_id = _make_mock_channel_id()
    msg = _make_mock_message(channel_id)
    assert queue.qsize() == 0
    queue.put_nowait(msg)
    assert queue.qsize() == len(msg.data) + HEADER_SIZE
    assert not under_water_callbacks
    queue.put_nowait(msg)  # now 2 messages
    assert not under_water_callbacks
    queue.put_nowait(msg)  # now 3 messages
    assert not under_water_callbacks
    queue.put_nowait(msg)  # now 4 messages -- under water
    assert under_water_callbacks == [True]
    queue.put_nowait(msg)  # now 5 messages -- still under water
    assert under_water_callbacks == [True]
    queue.get_nowait()  # now 4 messages -- have not reached low watermark
    assert under_water_callbacks == [True]
    queue.get_nowait()  # now 3 messages -- have not reached low watermark
    assert under_water_callbacks == [True]
    queue.get_nowait()  # now 2 messages -- reached low watermark
    assert under_water_callbacks == [True, False]
    queue.get_nowait()  # now 1 message -- still below low watermark
    assert under_water_callbacks == [True, False]
    queue.get_nowait()  # now 0 messages -- empty
    assert under_water_callbacks == [True, False]
    queue.put_nowait(msg)  # now 1 message -- below high watermark
    assert under_water_callbacks == [True, False]
    queue.put_nowait(msg)  # now 2 messages -- still below high watermark
    assert under_water_callbacks == [True, False]
    queue.put_nowait(msg)  # now 3 messages -- still below high watermark
    assert under_water_callbacks == [True, False]
    queue.put_nowait(msg)  # now 4 messages -- reached high watermark
    assert under_water_callbacks == [True, False, True]
    queue.get_nowait()  # now 3 messages -- below high watermark, but still above low watermark
    assert under_water_callbacks == [True, False, True]
    queue.get_nowait()  # now 2 messages -- below high watermark and below low watermark
    assert under_water_callbacks == [True, False, True, False]
