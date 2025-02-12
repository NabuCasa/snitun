"""Test client connector."""

import asyncio
import ipaddress
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from snitun.client.connector import Connector, ConnectorHandler
from snitun.exceptions import MultiplexerTransportClose
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer

from ..conftest import Client

IP_ADDR = ipaddress.ip_address("8.8.8.8")
BAD_ADDR = ipaddress.ip_address("8.8.1.1")


async def test_init_connector(
    test_endpoint: list[Client],
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test and init a connector."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.close.set()


async def test_flow_connector(
    test_endpoint: list[Client],
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test and and perform a connector flow."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
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
    test_endpoint: list[Client],
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test and init a connector with remote close."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
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

    await multiplexer_server.delete_channel(channel)
    data = await test_connection.reader.read(1024)
    assert not data

    test_connection.close.set()


async def test_close_connector_local(
    test_endpoint: list[Client],
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test and init a connector."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
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
    test_endpoint: list[Client],
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test and init a connector with whitelist."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822", True)
    multiplexer_client._new_connections = connector.handler

    connector.whitelist.add(IP_ADDR)
    assert IP_ADDR in connector.whitelist
    channel = await multiplexer_server.create_channel(IP_ADDR, lambda _: None)
    await asyncio.sleep(0.1)

    assert test_endpoint
    test_connection = test_endpoint[0]

    await channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.close.set()


async def test_init_connector_whitelist_bad(
    test_endpoint: list[Client],
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test and init a connector with whitelist bad requests."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822", True)
    multiplexer_client._new_connections = connector.handler

    connector.whitelist.add(IP_ADDR)
    assert IP_ADDR in connector.whitelist
    assert BAD_ADDR not in connector.whitelist
    channel = await multiplexer_server.create_channel(BAD_ADDR, lambda _: None)
    await asyncio.sleep(0.1)

    assert not test_endpoint

    with pytest.raises(MultiplexerTransportClose):
        await channel.read()


async def test_connector_error_callback(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test connector endpoint error callback."""
    callback = AsyncMock()
    connector = Connector("127.0.0.1", "8822", False, callback)

    channel = await multiplexer_client.create_channel(IP_ADDR, lambda _: None)

    callback.assert_not_called()

    with patch("asyncio.open_connection", side_effect=OSError("Lorem ipsum...")):
        await connector.handler(multiplexer_client, channel)

    callback.assert_called_once()


async def test_connector_handler_can_pause(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    test_endpoint: list[Client],
) -> None:
    """Test connector handler can pause."""
    assert not test_endpoint

    connector = Connector("127.0.0.1", "8822")
    multiplexer_client._new_connections = connector.handler

    connector_handler: ConnectorHandler | None = None

    def save_connector_handler(
        loop: asyncio.AbstractEventLoop,
        channel: MultiplexerChannel,
    ) -> ConnectorHandler:
        nonlocal connector_handler
        connector_handler = ConnectorHandler(loop, channel)
        return connector_handler

    with patch("snitun.client.connector.ConnectorHandler", save_connector_handler):
        server_channel = await multiplexer_server.create_channel(
            IP_ADDR, lambda _: None,
        )
        await asyncio.sleep(0.1)

    assert isinstance(connector_handler, ConnectorHandler)
    handler = cast(ConnectorHandler, connector_handler)
    client_channel = handler._channel
    assert client_channel._pause_resume_reader_callback is not None
    assert (
        client_channel._pause_resume_reader_callback
        == handler._pause_resume_reader_callback
    )

    assert test_endpoint
    test_connection = test_endpoint[0]

    await server_channel.write(b"Hallo")
    data = await test_connection.reader.read(1024)
    assert data == b"Hallo"

    test_connection.writer.write(b"Hiro")
    await test_connection.writer.drain()

    data = await server_channel.read()
    assert data == b"Hiro"

    assert handler._pause_future is None
    client_channel.on_remote_input_under_water(True)
    assert handler._pause_future is not None

    await server_channel.write(b"Goodbye")
    data = await test_connection.reader.read(1024)
    assert data == b"Goodbye"

    test_connection.writer.write(b"Should read one more")
    await test_connection.writer.drain()
    assert await server_channel.read() == b"Should read one more"

    test_connection.writer.write(b"ByeBye")
    await test_connection.writer.drain()

    read_task = asyncio.create_task(server_channel.read())
    await asyncio.sleep(0.1)
    # Make sure reader is actually paused
    assert not read_task.done()

    # Now simulate that the remote input is no longer under water
    client_channel.on_remote_input_under_water(False)
    assert handler._pause_future is None
    data = await read_task
    assert data == b"ByeBye"

    test_connection.writer.close()
    test_connection.close.set()
    await asyncio.sleep(0.1)

    with pytest.raises(MultiplexerTransportClose):
        await server_channel.read()
