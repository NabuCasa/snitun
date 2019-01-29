"""Test Multiplexer channels."""
import asyncio
from uuid import UUID

import pytest

from snitun.exceptions import MultiplexerTransportError
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA,
                                        CHANNEL_FLOW_NEW, MultiplexerMessage)


async def test_initial_channel():
    """Test new MultiplexerChannel with UUID."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    await channel.new()
    assert not output.empty()

    message = output.get_nowait()
    assert message.channel_id == channel.uuid
    assert message.flow_type == CHANNEL_FLOW_NEW
    assert message.data == b""


async def test_close_channel():
    """Test close MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    await channel.close()
    assert not output.empty()

    message = output.get_nowait()
    assert message.channel_id == channel.uuid
    assert message.flow_type == CHANNEL_FLOW_CLOSE
    assert message.data == b""


async def test_write_data():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    await channel.write(b"test")
    assert not output.empty()

    message = output.get_nowait()
    assert message.channel_id == channel.uuid
    assert message.flow_type == CHANNEL_FLOW_DATA
    assert message.data == b"test"


async def test_read_data():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    message = MultiplexerMessage(channel.uuid, CHANNEL_FLOW_DATA, b"test")
    await channel._input.put(message)
    data = await channel.read()

    assert data == b"test"


async def test_read_data_on_close():
    """Test send data over MultiplexerChannel on close."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    message = MultiplexerMessage(channel.uuid, CHANNEL_FLOW_CLOSE)
    await channel._input.put(message)
    data = await channel.read()

    assert data is None


async def test_close_channel_transport_error():
    """Test close MultiplexerChannel transport error."""
    output = asyncio.Queue(1)
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    output.put_nowait(None)

    with pytest.raises(MultiplexerTransportError):
        await channel.close()


async def test_new_channel_transport_error():
    """Test new MultiplexerChannel transport error."""
    output = asyncio.Queue(1)
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    output.put_nowait(None)

    with pytest.raises(MultiplexerTransportError):
        await channel.new()
