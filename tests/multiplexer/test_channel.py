"""Test Multiplexer channels."""
import asyncio
from uuid import UUID

import pytest

from snitun.exceptions import (MultiplexerTransportClose,
                               MultiplexerTransportError)
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA,
                                        CHANNEL_FLOW_NEW, MultiplexerMessage)


async def test_initial_channel():
    """Test new MultiplexerChannel with UUID."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    message = channel.init_new()

    assert message.channel_id == channel.uuid
    assert message.flow_type == CHANNEL_FLOW_NEW
    assert message.data == b""


async def test_close_channel():
    """Test close MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    message = channel.init_close()

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

    with pytest.raises(MultiplexerTransportClose):
        data = await channel.read()


async def test_write_data_peer_error(raise_timeout):
    """Test send data over MultiplexerChannel but peer don't response."""
    output = asyncio.Queue(1)
    channel = MultiplexerChannel(output)
    assert isinstance(channel.uuid, UUID)

    # fill peer queue
    output.put_nowait(None)

    with pytest.raises(MultiplexerTransportError):
        await channel.write(b"test")
