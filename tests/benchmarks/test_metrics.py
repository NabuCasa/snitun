"""Benchmark tests for metrics collection performance."""

import asyncio
from unittest.mock import MagicMock

import pytest
from pytest_codspeed import BenchmarkFixture

from snitun.server.worker import ServerWorker


class MockPeer:
    """Mock peer for testing."""

    def __init__(self, hostname: str, protocol_version: int):
        """Initialize mock peer."""
        self.hostname = hostname
        self.protocol_version = protocol_version
        self.all_hostnames = [hostname]


@pytest.mark.parametrize("peer_count", [100, 1000, 5000, 10000, 20000])
def test_collect_and_report_metrics_performance(
    benchmark: BenchmarkFixture,
    peer_count: int,
) -> None:
    """Benchmark _collect_and_report_metrics with varying peer counts."""
    # Create worker with mock metrics
    mock_metrics = MagicMock()
    mock_factory = MagicMock(return_value=mock_metrics)

    worker = ServerWorker(
        fernet_keys=["Wnng8SA8nnad6Q4YiZCFVMBMvxMJfn9pvMY7Wg_JBtw="],
        metrics_factory=mock_factory,
        metrics_interval=60,  # Not used in this test
    )

    # Create mock peers with different protocol versions
    mock_peers = []
    for i in range(peer_count):
        # Distribute protocol versions: 60% v0, 30% v1, 10% v2
        if i < peer_count * 0.6:
            protocol_version = 0
        elif i < peer_count * 0.9:
            protocol_version = 1
        else:
            protocol_version = 2

        mock_peers.append(MockPeer(f"peer-{i}.example.com", protocol_version))

    # Setup worker with mock peers
    mock_peer_manager = MagicMock()
    mock_peer_manager.iter_peers = MagicMock(return_value=mock_peers)
    worker._peers = mock_peer_manager
    worker._metrics = mock_metrics

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    @benchmark
    def collect_metrics() -> None:
        """Run the metrics collection."""
        loop.run_until_complete(worker._collect_and_report_metrics())
