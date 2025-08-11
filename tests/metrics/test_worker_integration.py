"""Test metrics integration with ServerWorker."""

import asyncio
import contextlib
from unittest.mock import MagicMock, call, patch

import pytest

from snitun.server.worker import ServerWorker


@pytest.mark.asyncio
async def test_worker_metrics_reporting() -> None:
    """Test that worker reports metrics correctly with comprehensive assertions."""
    mock_metrics = MagicMock()
    mock_factory = MagicMock(return_value=mock_metrics)
    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
        metrics_factory=mock_factory,
        metrics_interval=0.1,  # 100ms for faster testing
    )

    with patch.object(worker, "_loop", asyncio.get_event_loop()):
        mock_peers = MagicMock()
        mock_peers._peers = {}
        mock_peers.iter_peers = MagicMock(return_value=[])
        worker._peers = mock_peers
        worker._metrics = mock_factory()

        worker._metrics_task = asyncio.create_task(worker._report_metrics_loop())

        await asyncio.sleep(0.35)  # Should trigger ~3 reports

        worker._metrics_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker._metrics_task

        assert mock_metrics.gauge.call_count >= 3
        mock_metrics.gauge.assert_has_calls(
            [
                call("snitun.worker.peer_connections", 0)
                for _ in range(mock_metrics.gauge.call_count)
            ],
        )


@pytest.mark.asyncio
async def test_worker_metrics_with_multiple_peers() -> None:
    """Test metrics reporting with multiple peers and different protocol versions."""
    mock_metrics = MagicMock()
    mock_factory = MagicMock(return_value=mock_metrics)
    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
        metrics_factory=mock_factory,
        metrics_interval=0.1,
    )

    mock_peer1 = MagicMock()
    mock_peer1.protocol_version = 0
    mock_peer1.hostname = "peer1.example.com"
    mock_peer2 = MagicMock()
    mock_peer2.protocol_version = 0
    mock_peer2.hostname = "peer2.example.com"
    mock_peer3 = MagicMock()
    mock_peer3.protocol_version = 1
    mock_peer3.hostname = "peer3.example.com"
    mock_peer4 = MagicMock()
    mock_peer4.protocol_version = 2
    mock_peer4.hostname = "peer4.example.com"

    with patch.object(worker, "_loop", asyncio.get_event_loop()):
        mock_peers = MagicMock()
        mock_peers.iter_peers = MagicMock(
            return_value=[mock_peer1, mock_peer2, mock_peer3, mock_peer4],
        )
        worker._peers = mock_peers
        worker._metrics = mock_factory()

        # Run one collection cycle
        await worker._collect_and_report_metrics()

        assert mock_metrics.gauge.called
        mock_metrics.gauge.assert_has_calls(
            [
                call("snitun.worker.peer_connections", 4),
                call(
                    "snitun.worker.peer_connections",
                    2,
                    {"protocol_version": "0"},
                ),
                call(
                    "snitun.worker.peer_connections",
                    1,
                    {"protocol_version": "1"},
                ),
                call(
                    "snitun.worker.peer_connections",
                    1,
                    {"protocol_version": "2"},
                ),
            ],
        )


def test_worker_with_noop_metrics() -> None:
    """Test that worker works with no-op metrics (default)."""
    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
    )
    assert worker._metrics_factory is not None
    collector = worker._metrics_factory()
    collector.gauge("test", 1.0)
    assert not hasattr(collector, "_metrics")


@pytest.mark.asyncio
async def test_worker_metrics_task_lifecycle() -> None:
    """Test that metrics task is properly managed during worker lifecycle."""
    mock_metrics = MagicMock()
    mock_factory = MagicMock(return_value=mock_metrics)
    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
        metrics_factory=mock_factory,
        metrics_interval=0.1,
    )

    with patch.object(worker, "_loop", asyncio.get_event_loop()):
        assert worker._metrics_task is None

        mock_peers = MagicMock()
        mock_peers.iter_peers = MagicMock(return_value=[])
        worker._peers = mock_peers

        await worker._async_init()

        assert worker._metrics_task is not None
        assert not worker._metrics_task.done()
        assert worker._metrics is not None

        await asyncio.sleep(0.15)

        assert mock_metrics.gauge.called

        worker._metrics_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker._metrics_task

        assert worker._metrics_task.done()


@pytest.mark.asyncio
async def test_metrics_collection_without_peers() -> None:
    """Test metrics collection when PeerManager is None."""
    mock_metrics = MagicMock()
    mock_factory = MagicMock(return_value=mock_metrics)

    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
        metrics_factory=mock_factory,
    )
    worker._metrics = mock_factory()
    worker._peers = None

    await worker._collect_and_report_metrics()

    mock_metrics.gauge.assert_has_calls(
        [
            call("snitun.worker.peer_connections", 0),
        ],
    )


@pytest.mark.asyncio
async def test_metrics_collection_with_no_metrics_collector() -> None:
    """Test that metrics collection handles None metrics collector gracefully."""
    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
    )

    mock_peers = MagicMock()
    mock_peers.iter_peers = MagicMock(return_value=[])
    worker._peers = mock_peers
    worker._metrics = None

    try:
        await worker._collect_and_report_metrics()
    except BaseException:  # noqa: BLE001
        pytest.fail("Metrics collection with None collector raised an error")


@pytest.mark.asyncio
async def test_metrics_reporting_interval() -> None:
    """Test that metrics are reported at the correct interval."""
    mock_metrics = MagicMock()
    mock_factory = MagicMock(return_value=mock_metrics)

    interval = 0.2  # 200ms
    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
        metrics_factory=mock_factory,
        metrics_interval=interval,
    )

    with patch.object(worker, "_loop", asyncio.get_event_loop()):
        mock_peers = MagicMock()
        mock_peers.iter_peers = MagicMock(return_value=[])
        worker._peers = mock_peers
        worker._metrics = mock_factory()

        worker._metrics_task = asyncio.create_task(worker._report_metrics_loop())

        await asyncio.sleep(interval * 2.8)

        assert 2 <= mock_metrics.gauge.call_count <= 3

        await asyncio.sleep(interval * 1.2)

        assert mock_metrics.gauge.call_count >= 3

        worker._metrics_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker._metrics_task
