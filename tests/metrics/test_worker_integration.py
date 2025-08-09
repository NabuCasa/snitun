"""Test metrics integration with ServerWorker."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from snitun.server.worker import ServerWorker


@pytest.mark.asyncio
async def test_worker_metrics_reporting():
    """Test that worker reports metrics correctly."""
    # Create a mock metrics collector
    mock_metrics = MagicMock()
    mock_factory = MagicMock(return_value=mock_metrics)

    # Create worker with short metrics interval for testing
    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
        metrics_factory=mock_factory,
        metrics_interval=1,  # 1 second for faster testing
    )

    # Simulate the async_init without actually starting the process
    with patch.object(worker, "_loop", asyncio.get_event_loop()):
        # Mock the PeerManager to avoid actual network operations
        mock_peers = MagicMock()
        mock_peers._peers = {}
        worker._peers = mock_peers
        worker._metrics = mock_factory()

        # Create and start the metrics task
        worker._metrics_task = asyncio.create_task(worker._report_metrics_loop())

        # Let it run for a bit more than the interval
        await asyncio.sleep(1.5)

        # Cancel the task
        worker._metrics_task.cancel()
        try:
            await worker._metrics_task
        except asyncio.CancelledError:
            pass

        # Check that metrics were reported
        assert mock_metrics.gauge.called

        # Check the specific metrics calls
        calls = mock_metrics.gauge.call_args_list
        metric_names = [call[0][0] for call in calls]

        assert "snitun.worker.peer_connections" in metric_names


def test_worker_with_noop_metrics():
    """Test that worker works with no-op metrics (default)."""
    # Create worker without metrics factory
    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
    )

    # Should use no-op collector by default
    assert worker._metrics_factory is not None

    # Create the collector
    collector = worker._metrics_factory()

    # Should do nothing
    collector.gauge("test", 1.0)
    assert not hasattr(collector, "_metrics")
