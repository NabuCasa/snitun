"""Test metrics factory functions."""

from snitun.metrics import create_noop_metrics_collector
from snitun.metrics.noop import NoOpMetricsCollector


def test_create_noop_metrics_collector() -> None:
    """Test no-op metrics collector factory."""
    collector = create_noop_metrics_collector()

    assert isinstance(collector, NoOpMetricsCollector)

    collector.gauge("test", 1.0)

    assert not hasattr(collector, "_metrics")
