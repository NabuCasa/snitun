"""Tests for core multiplexer transport."""

import asyncio
from asyncio import sslproto
import ssl
from unittest.mock import patch

import pytest

from snitun.exceptions import MultiplexerTransportClose, MultiplexerTransportError
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.message import CHANNEL_FLOW_DATA, MultiplexerMessage
from snitun.multiplexer.transport import ChannelTransport

from ..conftest import IP_ADDR


class PatchableMultiplexerChannel(MultiplexerChannel):
    """MultiplexerChannel that can be patched since it uses __slots__."""


async def test_stopping_transport_reader_does_not_swallow_cancellation(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test that stopping transport does not swallow cancellation."""
    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    transport = ChannelTransport(channel, multiplexer_server)
    transport.start_reader()
    task = asyncio.create_task(transport.stop_reader())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_channel_read_on_closed_channel(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test reading on a closed channel."""
    with patch(
        "snitun.multiplexer.core.MultiplexerChannel",
        PatchableMultiplexerChannel,
    ):
        channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    with patch.object(channel, "read", side_effect=MultiplexerTransportClose):
        transport = ChannelTransport(channel, multiplexer_server)
        transport.start_reader()
        await asyncio.sleep(0)

    assert transport.is_closing() is True
    await transport.stop_reader()


async def test_pausing_and_resuming_the_transport(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test pausing and resuming the transport."""
    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    channel.message_transport(
        MultiplexerMessage(channel.id, CHANNEL_FLOW_DATA, b"test"),
    )

    class _MockProtocol(asyncio.BufferedProtocol):
        def __init__(self) -> None:
            self.buffer = memoryview(bytearray(16))
            self.buffer_updated_size = 0

        def buffer_updated(self, nbytes: int) -> None:
            self.buffer_updated_size = nbytes

        def get_buffer(self, sizehint: int) -> memoryview:
            return self.buffer

    protocol = _MockProtocol()
    transport = ChannelTransport(channel, multiplexer_server)
    transport.set_protocol(protocol)
    transport.pause_reading()
    assert transport.is_reading() is False
    transport.start_reader()
    assert transport.is_reading() is False
    transport.pause_reading()
    assert transport.is_reading() is False
    transport.resume_reading()
    assert transport.is_reading() is True

    await asyncio.sleep(0)

    assert bytes(protocol.buffer[0 : protocol.buffer_updated_size]) == b"test"
    assert transport.is_closing() is False
    await transport.stop_reader()
    assert transport.is_closing() is True


async def test_pausing_and_resuming_the_protocol(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test pausing and resuming the protocol."""
    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    channel.message_transport(
        MultiplexerMessage(channel.id, CHANNEL_FLOW_DATA, b"test"),
    )

    class _MockProtocol(asyncio.BufferedProtocol):
        def __init__(self) -> None:
            self.buffer = memoryview(bytearray(16))
            self.buffer_updated_size = 0

        def buffer_updated(self, nbytes: int) -> None:
            self.buffer_updated_size = nbytes

        def pause_writing(self) -> None:
            """Pause writing."""

        def resume_writing(self) -> None:
            """Resume writing."""

        def get_buffer(self, sizehint: int) -> memoryview:
            return self.buffer

    protocol = _MockProtocol()
    transport = ChannelTransport(channel, multiplexer_server)

    transport.set_protocol(protocol)
    transport.pause_protocol()
    transport.start_reader()

    assert transport.protocol_paused is True
    transport.resume_protocol()
    assert transport.protocol_paused is False

    with (
        pytest.raises(SystemExit),
        patch.object(protocol, "pause_writing", side_effect=SystemExit),
    ):
        transport.pause_protocol()
    assert transport.protocol_paused is False

    with patch.object(protocol, "pause_writing", side_effect=Exception):
        transport.pause_protocol()
    assert transport.protocol_paused is False

    transport.pause_protocol()
    assert transport.protocol_paused is True

    with (
        pytest.raises(SystemExit),
        patch.object(protocol, "resume_writing", side_effect=SystemExit),
    ):
        transport.resume_protocol()
    assert transport.protocol_paused is True

    with patch.object(protocol, "resume_writing", side_effect=Exception):
        transport.resume_protocol()
    assert transport.protocol_paused is True

    transport.resume_protocol()
    assert transport.protocol_paused is False

    await transport.stop_reader()
    assert transport.is_closing() is True

    # Cannot pause if already closing
    transport.pause_protocol()
    assert transport.protocol_paused is False


async def test_exception_channel_read(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test reading on a closed channel."""
    with patch(
        "snitun.multiplexer.core.MultiplexerChannel",
        PatchableMultiplexerChannel,
    ):
        channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    with patch.object(channel, "read", side_effect=Exception):
        transport = ChannelTransport(channel, multiplexer_server)
        transport.start_reader()
        await asyncio.sleep(0)

    assert transport.is_closing() is True
    await transport.stop_reader()


async def test_keyboard_interrupt_channel_read_eager(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test the transport does not swallow SystemExit."""
    with patch(
        "snitun.multiplexer.core.MultiplexerChannel",
        PatchableMultiplexerChannel,
    ):
        channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    with (
        patch.object(channel, "read", side_effect=SystemExit),
    ):
        transport = ChannelTransport(channel, multiplexer_server)
        with pytest.raises(SystemExit):
            transport.start_reader()


async def test_write_after_channel_close(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test write when channel raises MultiplexerTransportClose."""
    with patch(
        "snitun.multiplexer.core.MultiplexerChannel",
        PatchableMultiplexerChannel,
    ):
        channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    transport = ChannelTransport(channel, multiplexer_server)
    with patch.object(channel, "write_no_wait", side_effect=MultiplexerTransportClose):
        transport.write(b"test")

    assert transport.is_closing() is True


async def test_write_queue_full(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test write when channel raises MultiplexerTransportError (queue full)."""
    with patch(
        "snitun.multiplexer.core.MultiplexerChannel",
        PatchableMultiplexerChannel,
    ):
        channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    transport = ChannelTransport(channel, multiplexer_server)
    with patch.object(channel, "write_no_wait", side_effect=MultiplexerTransportError):
        transport.write(b"test")

    assert transport.is_closing() is True


async def test_force_close_twice_during_tls_handshake(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test connection_lost reaches SSLProtocol once when force closed twice.

    A server-side start_tls() SSLProtocol clears its app protocol when
    connection_lost() is called mid-handshake, so a second call raises
    AttributeError in the event loop.
    """
    loop = asyncio.get_running_loop()
    exceptions: list[dict] = []
    loop.set_exception_handler(lambda _loop, context: exceptions.append(context))

    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    transport = ChannelTransport(channel, multiplexer_server)
    ssl_protocol = sslproto.SSLProtocol(
        loop,
        asyncio.Protocol(),
        ssl.create_default_context(ssl.Purpose.CLIENT_AUTH),
        loop.create_future(),
        server_side=True,
        call_connection_made=False,
    )
    transport.set_protocol(ssl_protocol)
    ssl_protocol.connection_made(transport)

    with patch.object(
        ssl_protocol,
        "connection_lost",
        wraps=ssl_protocol.connection_lost,
    ) as connection_lost:
        # e.g. the reader sees the channel close and a write fails
        transport._force_close(None)
        transport._force_close(None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert connection_lost.call_count == 1
    assert exceptions == []
    assert transport.is_closing() is True
