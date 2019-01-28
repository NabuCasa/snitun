"""Test Multiplexer channels."""
import asyncio
from uuid import UUID

from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA,
                                        CHANNEL_FLOW_NEW, MultiplexerMessage)


async def test_initial_channel():
    """Test new MultiplexerChannel with UUID."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.id, UUID)

    await channel.new()
    assert not output.empty()

    message = output.get_nowait()
    assert message.channel_id == channel.id
    assert message.flow_type == CHANNEL_FLOW_NEW
    assert message.data == b""


async def test_close_channel():
    """Test close MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.id, UUID)

    await channel.close()
    assert not output.empty()

    message = output.get_nowait()
    assert message.channel_id == channel.id
    assert message.flow_type == CHANNEL_FLOW_CLOSE
    assert message.data == b""


async def test_write_data():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.id, UUID)

    await channel.write(b"test")
    assert not output.empty()

    message = output.get_nowait()
    assert message.channel_id == channel.id
    assert message.flow_type == CHANNEL_FLOW_DATA
    assert message.data == b"test"


async def test_read_data():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.id, UUID)

    message = MultiplexerMessage(channel.id, CHANNEL_FLOW_DATA, b"test")
    await channel.input_queue.put(message)
    data = await channel.read()

    assert data == b"test"


async def test_read_data_on_close():
    """Test send data over MultiplexerChannel on close."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.id, UUID)

    message = MultiplexerMessage(channel.id, CHANNEL_FLOW_CLOSE, b"")
    await channel.input_queue.put(message)
    data = await channel.read()

    assert data is None
