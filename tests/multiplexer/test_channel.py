"""Test Multiplexer channels."""

import asyncio
import ipaddress

import pytest

from snitun.exceptions import MultiplexerTransportClose, MultiplexerTransportError
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.message import (
    CHANNEL_FLOW_CLOSE,
    CHANNEL_FLOW_DATA,
    CHANNEL_FLOW_NEW,
    MultiplexerChannelId,
    MultiplexerMessage,
)
from snitun.multiplexer import core
from unittest.mock import patch
from typing import Callable
from snitun.utils.ipaddress import ip_address_to_bytes
from collections import deque
IP_ADDR = ipaddress.ip_address("8.8.8.8")

@pytest.fixture
def deque_output() -> deque[MultiplexerMessage]:
    """Create a deque output."""
    return deque()


@pytest.fixture
def output(deque_output: deque) -> Callable[[MultiplexerMessage], None]:
    """Create a deque output."""
    def _write_to_output(message: MultiplexerMessage) -> None:
        """Write message to output."""
        deque_output.append(message)

    return _write_to_output

async def test_initial_channel_msg(output: Callable[[MultiplexerMessage], None]) -> None:
    """Test new MultiplexerChannel with id."""
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = channel.init_new()

    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_NEW
    assert message.data == b""
    assert message.extra == b"4" + ip_address_to_bytes(IP_ADDR)


async def test_close_channel_msg(output: Callable[[MultiplexerMessage], None]) -> None:
    """Test close MultiplexerChannel."""
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = channel.init_close()

    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_CLOSE
    assert message.data == b""


async def test_write_data(deque_output: deque[MultiplexerMessage], output: Callable[[MultiplexerMessage], None]) -> None:
    """Test send data over MultiplexerChannel."""
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    await channel.write(b"test")
    assert deque_output
    message = deque_output[0]
    assert message.id == channel.id
    assert message.flow_type == CHANNEL_FLOW_DATA
    assert message.data == b"test"


async def test_closing(output: Callable[[MultiplexerMessage], None]) -> None:
    """Test send data over MultiplexerChannel."""
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    assert not channel.closing
    channel.close()
    assert channel.closing


async def test_write_data_after_close(output: Callable[[MultiplexerMessage], None]) -> None:
    """Test send data over MultiplexerChannel."""
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)
    assert not channel.closing

    channel.close()

    with pytest.raises(MultiplexerTransportClose):
        await channel.write(b"test")

    assert channel.closing


async def test_write_data_empty(output: Callable[[MultiplexerMessage], None]) -> None:
    """Test send data over MultiplexerChannel."""
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    with pytest.raises(MultiplexerTransportError):
        await channel.write(b"")


async def test_read_data(output: Callable[[MultiplexerMessage], None]) -> None:
    """Test send data over MultiplexerChannel."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    message = MultiplexerMessage(channel.id, CHANNEL_FLOW_DATA, b"test")
    channel.message_transport(message)
    data = await channel.read()

    assert data == b"test"


async def test_read_data_on_close(output: Callable[[MultiplexerMessage], None]) -> None:
    """Test send data over MultiplexerChannel on close."""
    output = asyncio.Queue()
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)
    assert not channel.closing

    channel.close()
    with pytest.raises(MultiplexerTransportClose):
        await channel.read()

    assert channel.closing



async def test_message_transport_never_lock(output: Callable[[MultiplexerMessage], None]) -> None:
    """Message transport should never lock down."""
    channel = MultiplexerChannel(output, IP_ADDR)
    assert isinstance(channel.id, MultiplexerChannelId)

    for _ in range(1, 10000):
        channel.message_transport(channel.init_close())

    assert channel.healthy


async def test_write_throttling(event_loop: asyncio.AbstractEventLoop, deque_output: deque[MultiplexerMessage],output: Callable[[MultiplexerMessage], None]) -> None:
    """Message transport should never lock down."""
    loop = event_loop
    channel = MultiplexerChannel(output, IP_ADDR, throttling=0.1)
    assert isinstance(channel.id, MultiplexerChannelId)

    async def _write_background():
        """Write message in background."""
        for _ in range(1, 10000):
            await channel.write(b"test")

    background_task = loop.create_task(_write_background())

    await asyncio.sleep(0.3)
    assert not background_task.done()
    assert len(deque_output) <= 4

    background_task.cancel()
