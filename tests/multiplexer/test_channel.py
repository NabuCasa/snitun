"""Test Multiplexer channels."""

import asyncio
import ipaddress
from unittest.mock import patch

import pytest

from snitun.exceptions import MultiplexerTransportClose, MultiplexerTransportError
from snitun.multiplexer import channel as channel_module
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.const import (
    OUTGOING_QUEUE_HIGH_WATERMARK,
    OUTGOING_QUEUE_LOW_WATERMARK,
    OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
)
from snitun.multiplexer.message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    CHANNEL_FLOW_PAUSE,
    CHANNEL_FLOW_RESUME,
    HEADER_SIZE,
    MultiplexerChannelId,
    MultiplexerMessage,
)
from snitun.multiplexer.queue import MultiplexerMultiChannelQueue
from snitun.utils.ipaddress import ip_address_to_bytes

IP_ADDR = ipaddress.ip_address("8.8.8.8")


async def test_initial_channel_msg() -> None:
    """Test new MultiplexerChannel with id."""
    output = MultiplexerMultiChannelQueue(
        OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
        OUTGOING_QUEUE_LOW_WATERMARK,
        OUTGOING_QUEUE_HIGH_WATERMARK,
    )
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = channel.init_new()

    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_NEW
    assert message.data == b""
    assert message.extra == b"4" + ip_address_to_bytes(IP_ADDR)


async def test_close_channel_msg() -> None:
    """Test close MultiplexerChannel."""
    output = MultiplexerMultiChannelQueue(
        OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
        OUTGOING_QUEUE_LOW_WATERMARK,
        OUTGOING_QUEUE_HIGH_WATERMARK,
    )
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = channel.init_close()

    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_CLOSE
    assert message.data == b""


async def test_write_data() -> None:
    """Test send data over MultiplexerChannel."""
    output = MultiplexerMultiChannelQueue(
        OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
        OUTGOING_QUEUE_LOW_WATERMARK,
        OUTGOING_QUEUE_HIGH_WATERMARK,
    )
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    await channel.write(b"test")
    assert not output.empty(channel.id)

    message = output.get_nowait()
    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_DATA
    assert message.data == b"test"


async def test_closing() -> None:
    """Test send data over MultiplexerChannel."""
    output = MultiplexerMultiChannelQueue(
        OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
        OUTGOING_QUEUE_LOW_WATERMARK,
        OUTGOING_QUEUE_HIGH_WATERMARK,
    )
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    assert not channel.closing
    channel.close()
    assert channel.closing


async def test_write_data_after_close() -> None:
    """Test send data over MultiplexerChannel."""
    output = MultiplexerMultiChannelQueue(
        OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
        OUTGOING_QUEUE_LOW_WATERMARK,
        OUTGOING_QUEUE_HIGH_WATERMARK,
    )
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)
    assert not channel.closing

    channel.close()

    with pytest.raises(MultiplexerTransportClose):
        await channel.write(b"test")

    assert channel.closing


async def test_write_data_empty() -> None:
    """Test send data over MultiplexerChannel."""
    output = MultiplexerMultiChannelQueue(
        OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
        OUTGOING_QUEUE_LOW_WATERMARK,
        OUTGOING_QUEUE_HIGH_WATERMARK,
    )
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    with pytest.raises(MultiplexerTransportError):
        await channel.write(b"")


async def test_read_data() -> None:
    """Test send data over MultiplexerChannel."""
    output = MultiplexerMultiChannelQueue(
        OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
        OUTGOING_QUEUE_LOW_WATERMARK,
        OUTGOING_QUEUE_HIGH_WATERMARK,
    )
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = MultiplexerMessage(channel.id, CHANNEL_FLOW_DATA, b"test")
    channel.message_transport(message)
    data = await channel.read()

    assert data == b"test"


async def test_read_data_on_close() -> None:
    """Test send data over MultiplexerChannel on close."""
    output = MultiplexerMultiChannelQueue(
        OUTGOING_QUEUE_MAX_BYTES_CHANNEL,
        OUTGOING_QUEUE_LOW_WATERMARK,
        OUTGOING_QUEUE_HIGH_WATERMARK,
    )
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)
    assert not channel.closing

    channel.close()
    with pytest.raises(MultiplexerTransportClose):
        await channel.read()

    assert channel.closing


async def test_write_data_peer_error(raise_timeout: None) -> None:
    """Test send data over MultiplexerChannel but peer don't response."""
    output = MultiplexerMultiChannelQueue(1, 1, 1)
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    # fill peer queue
    output.put_nowait(channel.id, None)

    with pytest.raises(MultiplexerTransportError):
        await channel.write(b"test")


async def test_write_data_no_wait_queue_full() -> None:
    """Test send data over MultiplexerChannel when the queue is full."""
    output = MultiplexerMultiChannelQueue(1, 1, 1)
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    # fill peer queue
    output.put_nowait(channel.id, None)

    with pytest.raises(MultiplexerTransportError):
        await channel.write_no_wait(b"test")


async def test_message_transport_never_lock() -> None:
    """Message transport should never lock down even when it goes unhealthy."""
    output = MultiplexerMultiChannelQueue(1, 1, 1)
    with patch.object(channel_module, "INCOMING_QUEUE_MAX_BYTES_CHANNEL", 1):
        channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)
    assert not channel.unhealthy
    assert not channel.closing

    for _ in range(3):
        channel.message_transport(channel.init_close())

    assert channel.unhealthy


async def test_write_throttling() -> None:
    """Message transport should never lock down."""
    loop = asyncio.get_running_loop()
    output = MultiplexerMultiChannelQueue(500, 1, 100)
    channel = MultiplexerChannel(output, IP_ADDR, throttling=0.1)
    assert isinstance(channel.id, MultiplexerChannelId)
    message = b"test"
    message_size = HEADER_SIZE + len(message)

    async def _write_background():
        """Write message in background."""
        for _ in range(1, 10000):
            await channel.write(message)

    background_task = loop.create_task(_write_background())

    await asyncio.sleep(0.3)
    assert not background_task.done()

    assert output.size(channel.id) <= message_size * 4

    background_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await background_task


async def test_channel_input_queue_goes_under_water() -> None:
    """Test when a channel input queue goes under water.

    The channel should inform the peer to pause the reader.
    """
    output = MultiplexerMultiChannelQueue(
        HEADER_SIZE * 2,
        HEADER_SIZE,
        HEADER_SIZE * 2,
    )
    with (
        patch.object(
            channel_module,
            "INCOMING_QUEUE_MAX_BYTES_CHANNEL",
            HEADER_SIZE * 10,
        ),
        patch.object(channel_module, "INCOMING_QUEUE_LOW_WATERMARK", HEADER_SIZE),
        patch.object(channel_module, "INCOMING_QUEUE_HIGH_WATERMARK", HEADER_SIZE * 2),
    ):
        channel = MultiplexerChannel(output, IP_ADDR)
        assert isinstance(channel.id, MultiplexerChannelId)

    # Fake some data coming from the remote
    data_msg = MultiplexerMessage(channel.id, CHANNEL_FLOW_DATA)
    channel.message_transport(data_msg)
    channel.message_transport(data_msg)
    # The input queue is now under water
    assert channel._input._under_water

    # We should have told the remote to pause
    assert output.get_nowait() == MultiplexerMessage(channel.id, CHANNEL_FLOW_PAUSE)

    await channel.read() == data_msg.data
    # The input queue is now back to normal

    # We should have told the remote to resume
    assert output.get_nowait() == MultiplexerMessage(channel.id, CHANNEL_FLOW_RESUME)


async def test_channel_input_queue_goes_under_water_output_full(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test when a channel input queue goes under water when output is full.

    The channel should inform the peer to pause the reader.
    """
    output = MultiplexerMultiChannelQueue(
        HEADER_SIZE * 2,
        HEADER_SIZE,
        HEADER_SIZE * 2,
    )
    with (
        patch.object(
            channel_module,
            "INCOMING_QUEUE_MAX_BYTES_CHANNEL",
            HEADER_SIZE * 10,
        ),
        patch.object(channel_module, "INCOMING_QUEUE_LOW_WATERMARK", HEADER_SIZE),
        patch.object(channel_module, "INCOMING_QUEUE_HIGH_WATERMARK", HEADER_SIZE * 2),
    ):
        channel = MultiplexerChannel(output, IP_ADDR)
        assert isinstance(channel.id, MultiplexerChannelId)

    data_msg = MultiplexerMessage(channel.id, CHANNEL_FLOW_DATA)

    # Fill the output queue so it's full
    output.put_nowait(channel.id, data_msg)
    output.put_nowait(channel.id, data_msg)

    # Fake some data coming from the remote
    channel.message_transport(data_msg)
    channel.message_transport(data_msg)
    # The input queue is now under water
    assert channel._input._under_water

    # We can't tell the remote to pause because
    # our output queue is full
    assert (
        f"{channel.id}: Cannot send pause/resume message to peer, "
        "output queue is full" in caplog.text
    )
