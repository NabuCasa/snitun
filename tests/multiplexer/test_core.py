"""Tests for core multiplexer handler."""

import asyncio
import ipaddress
from unittest.mock import patch

import pytest

from snitun.exceptions import MultiplexerTransportClose, MultiplexerTransportError
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.message import CHANNEL_FLOW_PING
from snitun.utils.asyncio import asyncio_timeout

IP_ADDR = ipaddress.ip_address("8.8.8.8")


async def test_init_multiplexer_server(test_server, test_client, crypto_transport):
    """Test to create a new Multiplexer from server socket."""
    client = test_server[0]

    multiplexer = Multiplexer(crypto_transport, client.reader, client.writer)

    assert multiplexer.is_connected
    assert multiplexer._throttling is None
    multiplexer.shutdown()
    client.close.set()


async def test_init_multiplexer_client(test_client, crypto_transport):
    """Test to create a new Multiplexer from client socket."""
    multiplexer = Multiplexer(crypto_transport, test_client.reader, test_client.writer)

    assert multiplexer.is_connected
    assert multiplexer._throttling is None
    multiplexer.shutdown()


async def test_init_multiplexer_server_throttling(
    test_server,
    test_client,
    crypto_transport,
):
    """Test to create a new Multiplexer from server socket."""
    client = test_server[0]

    multiplexer = Multiplexer(
        crypto_transport,
        client.reader,
        client.writer,
        throttling=500,
    )

    assert multiplexer.is_connected
    assert multiplexer._throttling == 0.002
    multiplexer.shutdown()
    client.close.set()


async def test_init_multiplexer_client_throttling(test_client, crypto_transport):
    """Test to create a new Multiplexer from client socket."""
    multiplexer = Multiplexer(
        crypto_transport,
        test_client.reader,
        test_client.writer,
        throttling=500,
    )

    assert multiplexer.is_connected
    assert multiplexer._throttling == 0.002
    multiplexer.shutdown()


async def test_multiplexer_server_close(multiplexer_server, multiplexer_client):
    """Test a close from server peers."""
    assert multiplexer_server.is_connected
    assert multiplexer_client.is_connected

    multiplexer_server.shutdown()
    await asyncio.sleep(0.1)

    assert not multiplexer_server.is_connected
    assert not multiplexer_client.is_connected


async def test_multiplexer_client_close(multiplexer_server, multiplexer_client):
    """Test a close from client peers."""
    assert multiplexer_server.is_connected
    assert multiplexer_client.is_connected

    multiplexer_client.shutdown()
    await asyncio.sleep(0.1)

    assert not multiplexer_server.is_connected
    assert not multiplexer_client.is_connected


async def test_multiplexer_ping(event_loop, test_server, multiplexer_client):
    """Test a ping between peers."""
    loop = event_loop
    client = test_server[0]
    ping_task = loop.create_task(multiplexer_client.ping())

    await asyncio.sleep(0.1)

    data = await client.reader.read(60)
    data = multiplexer_client._crypto.decrypt(data)
    assert data[16] == CHANNEL_FLOW_PING
    assert int.from_bytes(data[17:21], "big") == 0
    assert data[21:25] == b"ping"

    ping_task.cancel()


async def test_multiplexer_ping_error(event_loop, test_server, multiplexer_client):
    """Test a ping between peers."""
    from snitun.multiplexer import core as multi_core

    loop = event_loop
    multi_core.PEER_TCP_TIMEOUT = 0.2

    client = test_server[0]
    ping_task = loop.create_task(multiplexer_client.ping())

    await asyncio.sleep(0.3)

    data = await client.reader.read(60)
    data = multiplexer_client._crypto.decrypt(data)
    assert data[16] == CHANNEL_FLOW_PING
    assert int.from_bytes(data[17:21], "big") == 0
    assert data[21:25] == b"ping"

    assert ping_task.done()

    with pytest.raises(MultiplexerTransportError):
        raise ping_task.exception()

    multi_core.PEER_TCP_TIMEOUT = 90


async def test_multiplexer_ping_pong(multiplexer_client, multiplexer_server):
    """Test that without new channel callback can't create new channels."""
    await multiplexer_client.ping()
    assert multiplexer_client._healthy.is_set()


async def test_multiplexer_cant_init_channel(multiplexer_client, multiplexer_server):
    """Test that without new channel callback can't create new channels."""
    assert not multiplexer_client._channels
    assert not multiplexer_server._channels

    # Disable new channels
    multiplexer_server._new_connections = None

    await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    assert not multiplexer_server._channels


async def test_multiplexer_init_channel(multiplexer_client, multiplexer_server):
    """Test that new channels are created."""
    assert not multiplexer_client._channels
    assert not multiplexer_server._channels

    channel = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    assert multiplexer_server._channels

    assert multiplexer_client._channels[channel.id]
    assert multiplexer_server._channels[channel.id]
    assert multiplexer_client._channels[channel.id].ip_address == IP_ADDR
    assert multiplexer_server._channels[channel.id].ip_address == IP_ADDR


async def test_multiplexer_init_channel_full(multiplexer_client, raise_timeout):
    """Test that new channels are created but peer error is available."""
    assert not multiplexer_client._channels

    with pytest.raises(MultiplexerTransportError):
        channel = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels


async def test_multiplexer_close_channel(multiplexer_client, multiplexer_server):
    """Test that channels are nice removed."""
    assert not multiplexer_client._channels
    assert not multiplexer_server._channels

    channel = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels
    assert multiplexer_server._channels

    assert multiplexer_client._channels[channel.id]
    assert multiplexer_server._channels[channel.id]
    assert multiplexer_client._channels[channel.id].ip_address == IP_ADDR
    assert multiplexer_server._channels[channel.id].ip_address == IP_ADDR

    multiplexer_client.delete_channel(channel)
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels
    assert not multiplexer_server._channels


async def test_multiplexer_close_channel_full(multiplexer_client):
    """Test that channels are nice removed but peer error is available."""
    assert not multiplexer_client._channels

    channel = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert multiplexer_client._channels

    with patch.object(asyncio_timeout, "timeout", side_effect=asyncio.TimeoutError()):
        with pytest.raises(MultiplexerTransportError):
            channel = multiplexer_client.delete_channel(channel)
    await asyncio.sleep(0.1)

    assert not multiplexer_client._channels


async def test_multiplexer_data_channel(multiplexer_client, multiplexer_server):
    """Test that new channels are created."""
    assert not multiplexer_client._channels
    assert not multiplexer_server._channels

    channel_client = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    channel_server = multiplexer_server._channels.get(channel_client.id)

    assert channel_client
    assert channel_server

    await channel_client.write(b"test 1")
    await asyncio.sleep(0.1)
    data = await channel_server.read()
    assert data == b"test 1"

    await channel_server.write(b"test 2")
    await asyncio.sleep(0.1)
    data = await channel_client.read()
    assert data == b"test 2"


async def test_multiplexer_channel_shutdown(
    event_loop,
    multiplexer_client,
    multiplexer_server,
):
    """Test that new channels are created and graceful shutdown."""
    loop = event_loop

    assert not multiplexer_client._channels
    assert not multiplexer_server._channels

    channel_client = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    channel_server = multiplexer_server._channels.get(channel_client.id)

    client_read = loop.create_task(channel_client.read())
    server_read = loop.create_task(channel_server.read())

    assert not client_read.done()
    assert not server_read.done()

    multiplexer_client.shutdown()
    await asyncio.sleep(0.1)
    assert not multiplexer_client._channels
    assert client_read.done()

    with pytest.raises(MultiplexerTransportClose):
        raise client_read.exception()

    assert not multiplexer_server._channels
    assert server_read.done()

    with pytest.raises(MultiplexerTransportClose):
        raise server_read.exception()


async def test_multiplexer_data_channel_abort_full(
    multiplexer_client,
    multiplexer_server,
):
    """Test that new channels are created."""
    assert not multiplexer_client._channels
    assert not multiplexer_server._channels

    channel_client = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    channel_server = multiplexer_server._channels.get(channel_client.id)

    assert channel_client
    assert channel_server

    with pytest.raises(MultiplexerTransportClose):
        for count in range(1, 50000):
            await channel_client.write(b"test xxxx")

    with pytest.raises(MultiplexerTransportClose):
        for count in range(1, 50000):
            data = await channel_server.read()

    await asyncio.sleep(0.1)
    assert not multiplexer_client._channels
    assert not multiplexer_server._channels


async def test_multiplexer_throttling(
    event_loop,
    multiplexer_client,
    multiplexer_server,
):
    """Test that new channels are created and graceful shutdown."""
    loop = event_loop

    assert not multiplexer_client._channels
    assert not multiplexer_server._channels
    data_in = []

    channel_client = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    channel_server = multiplexer_server._channels.get(channel_client.id)
    multiplexer_server._throttling = 0.1
    multiplexer_client._throttling = 0.1

    async def _sender():
        """Send data much as possible."""
        for count in range(1, 100000):
            await channel_client.write(b"data")

    async def _receiver():
        """Receive data much as possible."""
        for count in range(1, 100000):
            data = await channel_server.read()
            data_in.append(data)

    receiver = loop.create_task(_receiver())
    sender = loop.create_task(_sender())
    await asyncio.sleep(0.8)

    assert not sender.done()
    assert not receiver.done()
    assert len(data_in) <= 8

    receiver.cancel()
    sender.cancel()


async def test_multiplexer_core_peer_timeout(
    event_loop,
    multiplexer_client,
    multiplexer_server,
):
    """Test that new channels are created and graceful shutdown."""
    from snitun.multiplexer import core as multi_core

    loop = event_loop
    multi_core.PEER_TCP_TIMEOUT = 0.2

    assert not multiplexer_client._channels
    assert not multiplexer_server._channels

    channel_client = await multiplexer_client.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    channel_server = multiplexer_server._channels.get(channel_client.id)

    client_read = loop.create_task(channel_client.read())
    server_read = loop.create_task(channel_server.read())

    assert not client_read.done()
    assert not server_read.done()

    await multiplexer_client.ping()
    await asyncio.sleep(0.3)

    assert not multiplexer_client._channels
    assert not multiplexer_server._channels
    assert server_read.done()
    assert client_read.done()

    with pytest.raises(MultiplexerTransportClose):
        raise server_read.exception()

    with pytest.raises(MultiplexerTransportClose):
        raise client_read.exception()

    multi_core.PEER_TCP_TIMEOUT = 90
