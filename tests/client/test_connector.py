"""Test client connector."""

import asyncio
import asyncio.sslproto
import ssl
from typing import cast
from unittest.mock import patch, AsyncMock

import aiohttp
from aiohttp import ClientConnectorError
import pytest

from snitun.client.connector import Connector,ConnectorHandler
from snitun.exceptions import MultiplexerTransportClose
from snitun.multiplexer.channel import MultiplexerChannel
from snitun.multiplexer.core import Multiplexer
from snitun.multiplexer.transport import ChannelTransport

from ..conftest import BAD_ADDR,IP_ADDR
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
    #test_endpoint: list[Client],
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test and init a connector with whitelist bad requests."""
    #assert not test_endpoint

    connector = Connector("127.0.0.1", "8822", True)
    multiplexer_client._new_connections = connector.handler

    connector.whitelist.add(IP_ADDR)
    assert IP_ADDR in connector.whitelist
    assert BAD_ADDR not in connector.whitelist
    channel = await multiplexer_server.create_channel(BAD_ADDR, lambda _: None)
    await asyncio.sleep(0.1)

    #assert not test_endpoint

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


async def test_connector_no_error_callback(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test connector with not endpoint error callback."""
    connector = Connector("127.0.0.1", "8822", False, None)
    channel = await multiplexer_client.create_channel(IP_ADDR, lambda _: None)
    with patch("asyncio.open_connection", side_effect=OSError("Lorem ipsum...")):
        await connector.handler(multiplexer_client, channel)


async def test_connector_handler_can_pause(
    multiplexer_client: Multiplexer,
    multiplexer_server: Multiplexer,
) -> None:
    """Test connector handler can pause."""
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
            IP_ADDR,
            lambda _: None,
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

    # TODO: replace protocol_factory with one that wrap TLS writes
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
    # Simulate that the remote input goes under water
    client_channel.on_remote_input_under_water(True)
    assert handler._pause_future is not None

    await server_channel.write(b"Goodbye")
    data = await test_connection.reader.read(1024)
    assert data == b"Goodbye"

    # This is an implementation detail that we might
    # change in the future, but for now we need to
    # to read one more message because we don't cancel
    # the current read when the reader pauses as the additional
    # complexity is not worth it.
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
