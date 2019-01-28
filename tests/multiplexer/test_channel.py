"""Test Multiplexer channels."""
import asyncio
from uuid import UUID

from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.message import (CHANNEL_FLOW_CLOSE, CHANNEL_FLOW_DATA,
                                        CHANNEL_FLOW_NEW)


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
