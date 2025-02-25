"""Test client connector."""

import asyncio
import asyncio.sslproto
import ssl
from typing import cast
from unittest.mock import patch

import aiohttp
from aiohttp import ClientConnectorError
import pytest

from snitun.client.connector import Connector
from snitun.exceptions import MultiplexerTransportClose
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.transport import ChannelTransport

from ..conftest import BAD_ADDR, IP_ADDR, SNITunLoopback, make_snitun_connector
from . import helpers


async def test_connector_disallowed_ip_address(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
) -> None:
    """End to end test from connecting from a non-whitelisted IP."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(
        multiplexer_server,
        client_ssl_context,
        ip_address=BAD_ADDR,
    )
    session = aiohttp.ClientSession(connector=connector)
    with pytest.raises(ClientConnectorError, match="Connection aborted by remote host"):
        await session.get("https://localhost:4242/does-not-exist")
    await session.close()


async def test_connector_missing_certificate(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector_missing_certificate: Connector,
    client_ssl_context: ssl.SSLContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End to end test that connector with a missing certificate."""
    multiplexer_client._new_connections = connector_missing_certificate.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)
    with pytest.raises(ClientConnectorError, match="Connection aborted by remote host"):
        await session.get("https://localhost:4242/")
    await session.close()
    assert "NO_SHARED_CIPHER" in caplog.text


async def test_connector_non_existent_url(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
) -> None:
    """End to end test that connector can fetch a non-existent URL."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)
    response = await session.get("https://localhost:4242/does-not-exist")
    assert response.status == 404
    await session.close()


async def test_connector_valid_url(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
) -> None:
    """End to end test that connector can fetch a non-existent URL."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)
    response = await session.get("https://localhost:4242/")
    assert response.status == 200
    content = await response.read()
    assert content == b"Hello world"
    await session.close()


async def test_connector_stream_large_file(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
) -> None:
    """End to end test that connector can fetch a non-existent URL."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)
    response = await session.get("https://localhost:4242/large_file")
    assert response.status == 200
    content: list[bytes] = []
    async for data, _ in response.content.iter_chunks():
        content.append(data)
    assert b"".join(content) == b"X" * 1024 * 1024 * 4
    await session.close()


async def test_connector_keep_alive_works(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
) -> None:
    """Test that HTTP keep alive works as expected."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    client_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal client_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        client_channel_transport = ChannelTransport(channel, multiplexer)
        return client_channel_transport

    with patch.object(helpers, "ChannelTransport", _save_transport):
        for _ in range(10):
            response = await session.get("https://localhost:4242/")
            assert response.status == 200
            content = await response.read()
            assert content == b"Hello world"

    await session.close()
    # Should only create one transport
    assert transport_creation_calls == 1


async def test_connector_multiple_connection(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
) -> None:
    """Test that that multiple concurrent requests make multiple connections."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    client_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal client_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        client_channel_transport = ChannelTransport(channel, multiplexer)
        return client_channel_transport

    async def _make_request() -> None:
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    with patch.object(helpers, "ChannelTransport", _save_transport):
        await asyncio.gather(*[_make_request() for _ in range(10)])

    await session.close()
    # Should create more than one transport
    assert transport_creation_calls > 1


async def test_connector_valid_url_empty_buffer_client_side(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
) -> None:
    """End to end test that connector fails when the buffer is empty."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    client_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal client_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        client_channel_transport = ChannelTransport(channel, multiplexer)
        return client_channel_transport

    with patch.object(helpers, "ChannelTransport", _save_transport):
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    # Simulate a broken buffering
    assert client_channel_transport is not None
    assert transport_creation_calls == 1
    ssl_proto = cast(
        asyncio.sslproto.SSLProtocol,
        client_channel_transport.get_protocol(),
    )
    assert client_channel_transport.is_reading
    # Simulate a buffer is empty
    with (
        pytest.raises(RuntimeError, match=r"get_buffer\(\) returned an empty buffer"),
        patch.object(ssl_proto, "get_buffer", return_value=b""),
    ):
        await session.get("https://localhost:4242/")

    await session.close()
    assert transport_creation_calls == 1


async def test_connector_valid_url_buffer_too_small_client_side(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
) -> None:
    """End to end test that connector fails when the buffer is too small."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    client_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal client_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        client_channel_transport = ChannelTransport(channel, multiplexer)
        return client_channel_transport

    with patch.object(helpers, "ChannelTransport", _save_transport):
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    assert client_channel_transport is not None
    assert transport_creation_calls == 1
    ssl_proto = cast(
        asyncio.sslproto.SSLProtocol,
        client_channel_transport.get_protocol(),
    )
    assert client_channel_transport.is_reading

    # Simulate a buffer is still too small
    with patch.object(ssl_proto, "get_buffer", return_value=memoryview(bytearray(1))):
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    await session.close()
    await connector.close()
    assert transport_creation_calls == 1


@pytest.mark.parametrize("exception", [MultiplexerTransportClose, Exception])
async def test_connector_valid_url_failed_to_get_buffer_unexpected_exception_client_side(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
    exception: Exception,
) -> None:
    """End to end test that connector fails when getting the buffer raises an exception."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    client_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal client_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        client_channel_transport = ChannelTransport(channel, multiplexer)
        return client_channel_transport

    with patch.object(helpers, "ChannelTransport", _save_transport):
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    # Simulate an exception getting the buffer
    assert client_channel_transport is not None
    assert transport_creation_calls == 1
    ssl_proto = cast(
        asyncio.sslproto.SSLProtocol,
        client_channel_transport.get_protocol(),
    )
    assert client_channel_transport.is_reading
    with (
        pytest.raises(exception),
        patch.object(ssl_proto, "get_buffer", side_effect=exception),
    ):
        await session.get("https://localhost:4242/")

    await session.close()
    assert transport_creation_calls == 1


@pytest.mark.parametrize("exception", [MultiplexerTransportClose, Exception])
async def test_connector_valid_url_buffer_updated_raises_client_side(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
    exception: Exception,
) -> None:
    """End to end test that connector fails when updating the buffer raises."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    client_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal client_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        client_channel_transport = ChannelTransport(channel, multiplexer)
        return client_channel_transport

    with patch.object(helpers, "ChannelTransport", _save_transport):
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    # Simulate an exception getting the buffer
    assert client_channel_transport is not None
    assert transport_creation_calls == 1
    ssl_proto = cast(
        asyncio.sslproto.SSLProtocol,
        client_channel_transport.get_protocol(),
    )
    assert client_channel_transport.is_reading
    with (
        pytest.raises(exception),
        patch.object(ssl_proto, "buffer_updated", side_effect=exception),
    ):
        await session.get("https://localhost:4242/")

    await session.close()
    assert transport_creation_calls == 1


async def test_connector_valid_url_empty_buffer_server_side(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End to end test that connector fails when the buffer is empty."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    server_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal server_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        server_channel_transport = ChannelTransport(channel, multiplexer)
        return server_channel_transport

    with patch("snitun.client.connector.ChannelTransport", _save_transport):
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    # Simulate a broken buffering
    assert server_channel_transport is not None
    assert transport_creation_calls == 1
    ssl_proto = cast(
        asyncio.sslproto.SSLProtocol,
        server_channel_transport.get_protocol(),
    )
    assert server_channel_transport.is_reading
    # Simulate a buffer is empty
    with (
        patch.object(ssl_proto, "get_buffer", return_value=b""),
    ):
        await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    await session.close()
    assert transport_creation_calls == 1
    assert "returned an empty buffer" in caplog.text


@pytest.mark.parametrize("exception", [MultiplexerTransportClose, Exception])
async def test_connector_valid_url_failed_to_get_buffer_unexpected_exception_server_side(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
    exception: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End to end test that connector fails when getting the buffer raises an exception."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    server_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal server_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        server_channel_transport = ChannelTransport(channel, multiplexer)
        return server_channel_transport

    with patch("snitun.client.connector.ChannelTransport", _save_transport):
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    # Simulate an exception getting the buffer
    assert server_channel_transport is not None
    assert transport_creation_calls == 1
    ssl_proto = cast(
        asyncio.sslproto.SSLProtocol,
        server_channel_transport.get_protocol(),
    )
    assert server_channel_transport.is_reading
    with (
        patch.object(ssl_proto, "get_buffer", side_effect=exception),
    ):
        # Should not need to read the buffer to get the
        # response as it should be transferred in start_tls
        await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    await session.close()
    assert transport_creation_calls == 1
    assert "consuming buffer or protocol.buffer_updated() call failed" in caplog.text


@pytest.mark.parametrize("exception", [MultiplexerTransportClose, Exception])
async def test_connector_valid_url_buffer_updated_raises_server_side(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    connector: Connector,
    client_ssl_context: ssl.SSLContext,
    exception: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End to end test that connector fails when updating the buffer raises."""
    multiplexer_client._new_connections = connector.handler
    connector = helpers.ChannelConnector(multiplexer_server, client_ssl_context)
    session = aiohttp.ClientSession(connector=connector)

    server_channel_transport: ChannelTransport | None = None
    transport_creation_calls = 0

    def _save_transport(
        channel: MultiplexerChannel,
        multiplexer: Multiplexer,
    ) -> ChannelTransport:
        nonlocal server_channel_transport, transport_creation_calls
        transport_creation_calls += 1
        server_channel_transport = ChannelTransport(channel, multiplexer)
        return server_channel_transport

    with patch("snitun.client.connector.ChannelTransport", _save_transport):
        response = await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    # Simulate an exception getting the buffer
    assert server_channel_transport is not None
    assert transport_creation_calls == 1
    ssl_proto = cast(
        asyncio.sslproto.SSLProtocol,
        server_channel_transport.get_protocol(),
    )
    assert server_channel_transport.is_reading
    with (
        patch.object(ssl_proto, "buffer_updated", side_effect=exception),
    ):
        # Should not need to read the buffer to get the
        # response as it should be transferred in start_tls
        await session.get("https://localhost:4242/")
        assert response.status == 200
        content = await response.read()
        assert content == b"Hello world"

    await session.close()
    assert transport_creation_calls == 1
    assert "consuming buffer or protocol.buffer_updated() call failed" in caplog.text


async def test_init_connector_whitelist_bad(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
    client_ssl_context: ssl.SSLContext,
    server_ssl_context: ssl.SSLContext,
) -> None:
    """Test and init a connector with whitelist bad requests."""
    connector_with_streams = make_snitun_connector(server_ssl_context, whitelist=True)
    connector = connector_with_streams.connector
    multiplexer_client._new_connections = connector.handler

    connector.whitelist.add(IP_ADDR)
    assert IP_ADDR in connector.whitelist
    assert BAD_ADDR not in connector.whitelist
    channel = await multiplexer_server.create_channel(BAD_ADDR, lambda _: None)
    await asyncio.sleep(0.1)

    assert not connector_with_streams.connections

    with pytest.raises(MultiplexerTransportClose):
        await channel.read()


async def test_connector_handler_can_pause(snitun_loopback: SNITunLoopback) -> None:
    """Test connector handler can pause."""
    client_channel = snitun_loopback.client.channel
    client_protocol = snitun_loopback.client.protocol
    client_transport = snitun_loopback.client.transport
    # In this case the server_protocol is the browser
    # and the client_protocol is the Home Assistant server
    # since the connection is initiated from the snitun server
    # back into Home Assistant
    server_protocol = snitun_loopback.server.protocol
    server_channel = snitun_loopback.server.channel

    server_protocol.writer.write(b"Hallo")
    await server_protocol.writer.drain()
    assert await client_protocol.reader.read(1024) == b"Hallo"

    client_protocol.writer.write(b"Hiro")
    await client_protocol.writer.drain()
    assert await server_protocol.reader.read(1024) == b"Hiro"

    assert client_transport.protocol_paused is False
    # Simulate that the remote input goes under water
    client_channel.on_remote_input_under_water(True)
    assert client_transport.protocol_paused is True

    client_protocol.writer.write(b"ByeBye")
    await client_protocol.writer.drain()

    read_task = asyncio.create_task(server_protocol.reader.read(1024))
    await asyncio.sleep(0.1)
    # Make sure reader is actually paused
    assert not read_task.done()

    # Now simulate that the remote input is no longer under water
    client_channel.on_remote_input_under_water(False)
    assert client_transport.protocol_paused is False
    assert await read_task == b"ByeBye"

    client_protocol.writer.close()
    await asyncio.sleep(0.1)

    with pytest.raises(MultiplexerTransportClose):
        await server_channel.read()

    # make sure writing to the transport after close swallows data
    # as its common for SSLProtocol to do this and we do not want
    # to raise and fill the logs with exceptions
    assert client_transport.is_closing() is True
    client_transport.write(b"write_after_close")
