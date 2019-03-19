"""Test Multiplexer channels."""
import asyncio
import ipaddress
from uuid import UUID

import pytest

from snitun.utils.ipaddress import ip_address_to_bytes
from snitun.exceptions import MultiplexerTransportClose, MultiplexerTransportError
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    MultiplexerMessage,
)

IP_ADDR = ipaddress.ip_address("8.8.8.8")


async def test_initial_channel_msg():
    """Test new MultiplexerChannel with UUID."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    message = channel.init_new()

    assert message.channel_id == channel.uuid
    assert message.flow_type == CHANNEL_FLOW_NEW
    assert message.data == b""
    assert message.extra == b"4" + ip_address_to_bytes(IP_ADDR)


async def test_close_channel_msg():
    """Test close MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    message = channel.init_close()

    assert message.channel_id == channel.uuid
    assert message.flow_type == CHANNEL_FLOW_CLOSE
    assert message.data == b""


async def test_write_data():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    await channel.write(b"test")
    assert not output.empty()

    message = output.get_nowait()
    assert message.channel_id == channel.uuid
    assert message.flow_type == CHANNEL_FLOW_DATA
    assert message.data == b"test"


async def test_write_data_after_close():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    channel.close()

    with pytest.raises(MultiplexerTransportClose):
        await channel.write(b"test")


async def test_write_data_empty():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    with pytest.raises(MultiplexerTransportError):
        await channel.write(b"")


async def test_read_data():
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    message = MultiplexerMessage(channel.uuid, CHANNEL_FLOW_DATA, b"test")
    channel.message_transport(message)
    data = await channel.read()

    assert data == b"test"


async def test_read_data_on_close():
    """Test send data over MultiplexerChannel on close."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    channel.close()
    with pytest.raises(MultiplexerTransportClose):
        data = await channel.read()


async def test_write_data_peer_error(raise_timeout):
    """Test send data over MultiplexerChannel but peer don't response."""
    output = asyncio.Queue(1)
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    # fill peer queue
    output.put_nowait(None)

    with pytest.raises(MultiplexerTransportError):
        await channel.write(b"test")


async def test_message_transport_never_lock():
    """Message transport should never lock down."""
    output = asyncio.Queue(1)
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.uuid, UUID)

    for _ in range(1, 20):
        channel.message_transport(channel.init_close())

    assert channel.error
