"""Tests for aiohttp snitun client."""

from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
import pytest
from pytest_aiohttp import AiohttpServer

from snitun.utils.aiohttp_client import SniTunClientAioHttp


async def test_init_client(aiohttp_server: AiohttpServer) -> None:
    """Init aiohttp client for test."""
    app = web.Application()
    server = await aiohttp_server(app)
    client = SniTunClientAioHttp(server.runner, None, "127.0.0.1")

    assert not client.is_connected


async def test_client_stop_no_wait(aiohttp_server: AiohttpServer) -> None:
    """Test that we do not wait if wait is not passed to the stop."""
    app = web.Application()
    server = await aiohttp_server(app)
    client = SniTunClientAioHttp(server.runner, None, "127.0.0.1")
    await client.stop()
    await client.stop(wait=True)
    assert not client.is_connected


async def test_endpoint_connection_error_callback_deprecated(
    aiohttp_server: AiohttpServer,
) -> None:
    """Test passing endpoint_connection_error_callback throws a warning."""
    app = web.Application()
    server = await aiohttp_server(app)
    client = SniTunClientAioHttp(server.runner, None, "127.0.0.1")
    with pytest.warns(
        DeprecationWarning,
        match=(
            r"Passing endpoint_connection_error_callback to SniTunClientAioHttp.start\(\)"
            r" is deprecated, is no longer used, and it will be removed in the future."
        ),
    ):
        await client.start(False, endpoint_connection_error_callback=AsyncMock())
    await client.stop(wait=True)
    assert not client.is_connected


async def test_client_connect_with_protocol_version() -> None:
    """Test connecting with a custom protocol version."""
    mock_client_peer = MagicMock()
    mock_client_peer.start = AsyncMock()
    mock_client_peer.is_connected = False

    mock_connector = MagicMock()

    mock_runner = MagicMock()
    mock_runner.server = MagicMock()

    with (
        patch("snitun.utils.aiohttp_client.ClientPeer", return_value=mock_client_peer),
        patch("snitun.utils.aiohttp_client.Connector", return_value=mock_connector),
    ):
        client = SniTunClientAioHttp(mock_runner, None, "127.0.0.1")

        await client.start()
        await client.connect(
            fernet_key=b"test_token",
            aes_key=b"0" * 32,
            aes_iv=b"0" * 16,
        )

        mock_client_peer.start.assert_called_once()
        args = mock_client_peer.start.call_args
        assert "protocol_version" in args.kwargs
        assert args.kwargs["protocol_version"] == 0  # DEFAULT_PROTOCOL_VERSION

        mock_client_peer.start.reset_mock()
        await client.connect(
            fernet_key=b"test_token",
            aes_key=b"0" * 32,
            aes_iv=b"0" * 16,
            protocol_version=0,
        )

        mock_client_peer.start.assert_called_once()
        args = mock_client_peer.start.call_args
        assert "protocol_version" in args.kwargs
        assert args.kwargs["protocol_version"] == 0
