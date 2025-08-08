"""Test metrics factory functions."""

from snitun.metrics import (
    create_default_metrics_collector,
    create_noop_metrics_collector,
)
from snitun.metrics.collector import DefaultMetricsCollector
from snitun.metrics.noop import NoOpMetricsCollector


def test_create_default_metrics_collector():
    """Test default metrics collector factory."""
    collector = create_default_metrics_collector()

    assert isinstance(collector, DefaultMetricsCollector)

    # Should be functional
    collector.gauge("test", 1.0)
    metrics = collector.get_metrics()
    assert len(metrics) == 1


def test_create_noop_metrics_collector():
    """Test no-op metrics collector factory."""
    collector = create_noop_metrics_collector()

    assert isinstance(collector, NoOpMetricsCollector)

    # Should do nothing
    collector.gauge("test", 1.0)
    assert not hasattr(collector, "_metrics")
