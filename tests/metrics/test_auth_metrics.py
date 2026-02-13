"""Test authentication metrics."""

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from snitun.exceptions import SniTunChallengeError, SniTunInvalidPeer
from snitun.server.listener_peer import PeerListener
from snitun.server.peer_manager import PeerManager


@pytest.mark.asyncio
async def test_auth_success_metrics() -> None:
    """Test that successful authentication increments the right metrics."""
    mock_metrics = MagicMock()
    mock_peer_manager = MagicMock(spec=PeerManager)
    mock_peer = MagicMock()
    mock_peer.is_connected = False
    mock_peer.init_multiplexer_challenge = AsyncMock()
    mock_peer_manager.create_peer.return_value = mock_peer

    listener = PeerListener(mock_peer_manager, metrics=mock_metrics)
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.transport.is_closing.return_value = False

    await listener.handle_connection(reader, writer, data=b"test_token")

    assert mock_metrics.increment.call_count == 2
    mock_metrics.increment.assert_has_calls(
        [
            call("snitun.auth.attempts", tags={"result": "started"}),
            call("snitun.auth.attempts", tags={"result": "success"}),
        ],
    )


@pytest.mark.asyncio
async def test_auth_invalid_token_metrics() -> None:
    """Test that invalid token increments failure metrics."""
    mock_metrics = MagicMock()
    mock_peer_manager = MagicMock(spec=PeerManager)
    mock_peer_manager.create_peer.side_effect = SniTunInvalidPeer("Invalid token")

    listener = PeerListener(mock_peer_manager, metrics=mock_metrics)
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.transport.is_closing.return_value = False

    await listener.handle_connection(reader, writer, data=b"invalid_token")

    assert mock_metrics.increment.call_count == 2
    mock_metrics.increment.assert_has_calls(
        [
            call("snitun.auth.attempts", tags={"result": "started"}),
            call("snitun.auth.failures", tags={"reason": "invalid_token"}),
        ],
    )


@pytest.mark.asyncio
async def test_auth_challenge_failed_metrics() -> None:
    """Test that challenge failure increments failure metrics."""
    mock_metrics = MagicMock()
    mock_peer_manager = MagicMock(spec=PeerManager)
    mock_peer = MagicMock()
    mock_peer.init_multiplexer_challenge = AsyncMock(
        side_effect=SniTunChallengeError("Challenge failed"),
    )
    mock_peer_manager.create_peer.return_value = mock_peer

    listener = PeerListener(mock_peer_manager, metrics=mock_metrics)
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.transport.is_closing.return_value = False

    await listener.handle_connection(reader, writer, data=b"test_token")

    assert mock_metrics.increment.call_count == 2
    mock_metrics.increment.assert_has_calls(
        [
            call("snitun.auth.attempts", tags={"result": "started"}),
            call("snitun.auth.failures", tags={"reason": "challenge_failed"}),
        ],
    )


@pytest.mark.asyncio
async def test_no_metrics_does_not_crash() -> None:
    """Test that listener works without metrics."""
    mock_peer_manager = MagicMock(spec=PeerManager)
    mock_peer = MagicMock()
    mock_peer.is_connected = False
    mock_peer.init_multiplexer_challenge = AsyncMock()
    mock_peer_manager.create_peer.return_value = mock_peer

    listener = PeerListener(mock_peer_manager, metrics=None)
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.transport.is_closing.return_value = False

    await listener.handle_connection(reader, writer, data=b"test_token")

    mock_peer_manager.create_peer.assert_called_once()
