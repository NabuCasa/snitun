"""Tests for aiohttp snitun client."""

from unittest.mock import AsyncMock, MagicMock, patch

from snitun.utils.aiohttp_client import SniTunClientAioHttp


async def test_init_client() -> None:
    """Init aiohttp client for test."""
    with patch("snitun.utils.aiohttp_client.SockSite"):
        client = SniTunClientAioHttp(None, None, "127.0.0.1")

    assert not client.is_connected


async def test_client_stop_no_wait() -> None:
    """Test that we do not wait if wait is not passed to the stop"""
    with patch("snitun.utils.aiohttp_client.SockSite"):
        client = SniTunClientAioHttp(None, None, "127.0.0.1")

    with patch(
        "snitun.utils.aiohttp_client._async_waitfor_socket_closed",
    ) as waitfor_socket_closed:
        waitfor_socket_closed.assert_not_called()
        await client.stop()
        waitfor_socket_closed.assert_not_called()

        await client.stop(wait=True)
        waitfor_socket_closed.assert_called()


async def test_client_connect_with_protocol_version() -> None:
    """Test connecting with a custom protocol version."""
    mock_client_peer = MagicMock()
    mock_client_peer.start = AsyncMock()
    mock_client_peer.is_connected = False

    mock_connector = MagicMock()

    mock_site = MagicMock()
    mock_site.start = AsyncMock()

    with (
        patch("snitun.utils.aiohttp_client.SockSite", return_value=mock_site),
        patch("snitun.utils.aiohttp_client.ClientPeer", return_value=mock_client_peer),
        patch("snitun.utils.aiohttp_client.Connector", return_value=mock_connector),
    ):
        client = SniTunClientAioHttp(None, None, "127.0.0.1")

        await client.start()
        await client.connect(
            fernet_key=b"test_token",
            aes_key=b"0" * 32,
            aes_iv=b"0" * 16,
        )

        mock_client_peer.start.assert_called_once()
        args = mock_client_peer.start.call_args
        assert "protocol_version" in args.kwargs
        assert args.kwargs["protocol_version"] == 1  # Default PROTOCOL_VERSION

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
