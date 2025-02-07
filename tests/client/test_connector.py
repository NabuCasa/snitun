"""Test client connector."""

import asyncio
import ipaddress
from unittest.mock import AsyncMock, patch

import pytest

from snitun.client.connector import Connector
from snitun.exceptions import MultiplexerTransportClose

IP_ADDR = ipaddress.ip_address("8.8.8.8")
BAD_ADDR = ipaddress.ip_address("8.8.1.1")


async def test_init_connector(test_endpoint, multiplexer_client, multiplexer_server):
    """Test and init a connector."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    channel = await multiplexer_server.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.close.set()


async def test_flow_connector(test_endpoint, multiplexer_client, multiplexer_server):
    """Test and and perform a connector flow."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    channel = await multiplexer_server.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.writer.write(b"Hiro")
    await test_connection.writer.drain()

    data = await channel.read()
    assert data == b"Hiro"

    test_connection.close.set()


async def test_close_connector_remote(
    test_endpoint,
    multiplexer_client,
    multiplexer_server,
):
    """Test and init a connector with remote close."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    channel = await multiplexer_server.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.writer.write(b"Hiro")
    await test_connection.writer.drain()

    data = await channel.read()
    assert data == b"Hiro"

    multiplexer_server.delete_channel(channel)
    data = await test_connection.reader.read(1024)
    assert not data

    test_connection.close.set()


async def test_close_connector_local(
    test_endpoint,
    multiplexer_client,
    multiplexer_server,
):
    """Test and init a connector."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    channel = await multiplexer_server.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.writer.write(b"Hiro")
    await test_connection.writer.drain()

    data = await channel.read()
    assert data == b"Hiro"

    test_connection.writer.close()
    test_connection.close.set()
    await asyncio.sleep(0.1)

    with pytest.raises(MultiplexerTransportClose):
        await channel.read()


async def test_init_connector_whitelist(
    test_endpoint,
    multiplexer_client,
    multiplexer_server,
):
    """Test and init a connector with whitelist."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822", True)
    multiplexer_client._new_connections = connector.handler

    connector.whitelist.add(IP_ADDR)
    assert IP_ADDR in connector.whitelist
    channel = await multiplexer_server.create_channel(IP_ADDR)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.close.set()


async def test_init_connector_whitelist_bad(
    test_endpoint,
    multiplexer_client,
    multiplexer_server,
):
    """Test and init a connector with whitelist bad requests."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822", True)
    multiplexer_client._new_connections = connector.handler

    connector.whitelist.add(IP_ADDR)
    assert IP_ADDR in connector.whitelist
    assert BAD_ADDR not in connector.whitelist
    channel = await multiplexer_server.create_channel(BAD_ADDR)
    await asyncio.sleep(0.1)

    assert not test_endpoint

    with pytest.raises(MultiplexerTransportClose):
        await channel.read()


async def test_connector_error_callback(multiplexer_client, multiplexer_server):
    """Test connector endpoint error callback."""
    callback = AsyncMock()
    connector = Connector("127.0.0.1", "8822", False, callback)

    channel = await multiplexer_server.create_channel(IP_ADDR)

    callback.assert_not_called()

    with patch("asyncio.open_connection", side_effect=OSError("Lorem ipsum...")):
        await connector.handler(multiplexer_client, channel)

    callback.assert_called_once()
