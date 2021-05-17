"""Test Multiplexer channels."""
import asyncio
import ipaddress

import pytest

from snitun.utils.ipaddress import ip_address_to_bytes
from snitun.exceptions import MultiplexerTransportClose, MultiplexerTransportError
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    MultiplexerMessage,
    MultiplexerChannelId,
)

IP_ADDR = ipaddress.ip_address("8.8.8.8")


async def test_initial_channel_msg():
    """Test new MultiplexerChannel with id."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = channel.init_new()

    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_NEW
    assert message.data == b""
    assert message.extra == b"4" + ip_address_to_bytes(IP_ADDR)


async def test_close_channel_msg():
    """Test close MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = channel.init_close()

    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_CLOSE
    assert message.data == b""


async def test_write_data():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    await channel.write(b"test")
    assert not output.empty()

    message = output.get_nowait()
    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_DATA
    assert message.data == b"test"


async def test_closing():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    assert not channel.closing
    channel.close()
    assert channel.closing


async def test_write_data_after_close():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)
    assert not channel.closing

    channel.close()

    with pytest.raises(MultiplexerTransportClose):
        await channel.write(b"test")

    assert channel.closing


async def test_write_data_empty():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    with pytest.raises(MultiplexerTransportError):
        await channel.write(b"")


async def test_read_data():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = MultiplexerMessage(channel.id, CHANNEL_FLOW_DATA, b"test")
    channel.message_transport(message)
    data = await channel.read()

    assert data == b"test"


async def test_read_data_on_close():
    """Test send data over MultiplexerChannel on close."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)
    assert not channel.closing

    channel.close()
    with pytest.raises(MultiplexerTransportClose):
        data = await channel.read()

    assert channel.closing


async def test_write_data_peer_error(raise_timeout):
    """Test send data over MultiplexerChannel but peer don't response."""
    output = asyncio.Queue(1)
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    # fill peer queue
    output.put_nowait(None)

    with pytest.raises(MultiplexerTransportError):
        await channel.write(b"test")


async def test_message_transport_never_lock():
    """Message transport should never lock down."""
    output = asyncio.Queue(1)
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    for _ in range(1, 10000):
        channel.message_transport(channel.init_close())

    assert channel.healthy


async def test_write_throttling(loop):
    """Message transport should never lock down."""
    output = asyncio.Queue(500)
    channel = MultiplexerChannel(output, IP_ADDR, throttling=0.1)
    assert isinstance(channel.id, MultiplexerChannelId)

    async def _write_background():
        """Write message in background."""
        for _ in range(1, 10000):
            await channel.write(b"test")

    background_task = loop.create_task(_write_background())

    await asyncio.sleep(0.3)
    assert not background_task.done()
    assert output.qsize() <= 4

    background_task.cancel()
