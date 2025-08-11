"""Test no-op metrics collector."""

from snitun.metrics.noop import NoOpMetricsCollector


def test_noop_collector_has_no_overhead() -> None:
    """Test that NoOp collector truly does nothing."""
    collector = NoOpMetricsCollector()

    collector.gauge("test", 1.0)
    collector.increment("test")
    collector.histogram("test", 1.0)
    collector.timing("test", 1.0)

    assert not hasattr(collector, "_metrics")
    assert not hasattr(collector, "_hostname")
    assert not hasattr(collector, "_process_id")


def test_noop_accepts_all_parameters() -> None:
    """Test that NoOp collector accepts all parameters without error."""
    collector = NoOpMetricsCollector()
    collector.gauge("test", 1.0, {"tag": "value"})
    collector.increment("test", 10, {"tag1": "v1", "tag2": "v2"})
    collector.histogram("test", 100.5, None)
    collector.timing("test", 50.0, {})
