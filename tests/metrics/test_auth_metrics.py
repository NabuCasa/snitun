"""Test authentication metrics."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from snitun.exceptions import SniTunChallengeError, SniTunInvalidPeer
from snitun.server.listener_peer import PeerListener
from snitun.server.peer_manager import PeerManager


@pytest.mark.asyncio
async def test_auth_success_metrics():
    """Test that successful authentication increments the right metrics."""
    # Create mock objects
    mock_metrics = MagicMock()
    mock_peer_manager = MagicMock(spec=PeerManager)
    mock_peer = MagicMock()
    mock_peer.is_connected = False
    mock_peer.init_multiplexer_challenge = AsyncMock()
    mock_peer_manager.create_peer.return_value = mock_peer

    # Create PeerListener with metrics
    listener = PeerListener(mock_peer_manager, metrics=mock_metrics)

    # Mock reader and writer
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.transport.is_closing.return_value = False

    # Test successful authentication
    await listener.handle_connection(reader, writer, data=b"test_token")

    # Verify metrics were incremented
    assert mock_metrics.increment.call_count == 2
    calls = mock_metrics.increment.call_args_list
    assert calls[0][0] == ("snitun.auth.attempts",)
    assert calls[0][1] == {"tags": {"result": "started"}}
    assert calls[1][0] == ("snitun.auth.attempts",)
    assert calls[1][1] == {"tags": {"result": "success"}}


@pytest.mark.asyncio
async def test_auth_invalid_token_metrics():
    """Test that invalid token increments failure metrics."""
    # Create mock objects
    mock_metrics = MagicMock()
    mock_peer_manager = MagicMock(spec=PeerManager)
    mock_peer_manager.create_peer.side_effect = SniTunInvalidPeer(
        "Invalid token")

    # Create PeerListener with metrics
    listener = PeerListener(mock_peer_manager, metrics=mock_metrics)

    # Mock reader and writer
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.transport.is_closing.return_value = False

    # Test invalid token
    await listener.handle_connection(reader, writer, data=b"invalid_token")

    # Verify metrics were incremented
    assert mock_metrics.increment.call_count == 2
    calls = mock_metrics.increment.call_args_list
    assert calls[0][0] == ("snitun.auth.attempts",)
    assert calls[0][1] == {"tags": {"result": "started"}}
    assert calls[1][0] == ("snitun.auth.failures",)
    assert calls[1][1] == {"tags": {"reason": "invalid_token"}}


@pytest.mark.asyncio
async def test_auth_challenge_failed_metrics():
    """Test that challenge failure increments failure metrics."""
    # Create mock objects
    mock_metrics = MagicMock()
    mock_peer_manager = MagicMock(spec=PeerManager)
    mock_peer = MagicMock()
    mock_peer.init_multiplexer_challenge = AsyncMock(
        side_effect=SniTunChallengeError("Challenge failed"),
    )
    mock_peer_manager.create_peer.return_value = mock_peer

    # Create PeerListener with metrics
    listener = PeerListener(mock_peer_manager, metrics=mock_metrics)

    # Mock reader and writer
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.transport.is_closing.return_value = False

    # Test challenge failure
    await listener.handle_connection(reader, writer, data=b"test_token")

    # Verify metrics were incremented
    assert mock_metrics.increment.call_count == 2
    calls = mock_metrics.increment.call_args_list
    assert calls[0][0] == ("snitun.auth.attempts",)
    assert calls[0][1] == {"tags": {"result": "started"}}
    assert calls[1][0] == ("snitun.auth.failures",)
    assert calls[1][1] == {"tags": {"reason": "challenge_failed"}}


@pytest.mark.asyncio
async def test_no_metrics_does_not_crash():
    """Test that listener works without metrics."""
    # Create mock objects
    mock_peer_manager = MagicMock(spec=PeerManager)
    mock_peer = MagicMock()
    mock_peer.is_connected = False
    mock_peer.init_multiplexer_challenge = AsyncMock()
    mock_peer_manager.create_peer.return_value = mock_peer

    # Create PeerListener without metrics
    listener = PeerListener(mock_peer_manager, metrics=None)

    # Mock reader and writer
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    writer.transport.is_closing.return_value = False

    # Test that it works without metrics
    await listener.handle_connection(reader, writer, data=b"test_token")

    # Should not crash and peer should be created
    mock_peer_manager.create_peer.assert_called_once()
