"""Test default metrics collector."""

import os
import socket

from snitun.metrics.collector import DefaultMetricsCollector


def test_default_collector_adds_system_tags():
    """Test that hostname and process_id are added automatically."""
    collector = DefaultMetricsCollector(hostname="test-host", process_id=12345)

    collector.gauge("test.metric", 42.0, {"custom": "tag"})

    # Verify metric has system tags
    metrics = collector.get_metrics()
    assert len(metrics) == 1

    key = list(metrics.keys())[0]
    metric = metrics[key]

    assert metric["tags"]["hostname"] == "test-host"
    assert metric["tags"]["process_id"] == "12345"
    assert metric["tags"]["custom"] == "tag"
    assert metric["value"] == 42.0


def test_default_collector_system_tags_override():
    """Test that system tags override user-provided tags."""
    collector = DefaultMetricsCollector(hostname="real-host", process_id=999)

    # Try to override system tags
    collector.gauge("test", 1.0, {"hostname": "fake", "process_id": "fake"})

    metrics = collector.get_metrics()
    key = list(metrics.keys())[0]
    metric = metrics[key]

    # System tags should win
    assert metric["tags"]["hostname"] == "real-host"
    assert metric["tags"]["process_id"] == "999"


def test_default_collector_defaults():
    """Test that collector uses system defaults when not specified."""
    collector = DefaultMetricsCollector()

    collector.gauge("test", 1.0)

    metrics = collector.get_metrics()
    key = list(metrics.keys())[0]
    metric = metrics[key]

    # Should have automatic hostname and process_id
    assert metric["tags"]["hostname"] == socket.gethostname()
    assert metric["tags"]["process_id"] == str(os.getpid())


def test_gauge_metric():
    """Test gauge metric updates."""
    collector = DefaultMetricsCollector(hostname="test", process_id=1)

    collector.gauge("cpu.usage", 45.5)
    collector.gauge("cpu.usage", 67.8)  # Should replace

    metrics = collector.get_metrics()
    assert len(metrics) == 1

    key = list(metrics.keys())[0]
    assert metrics[key]["value"] == 67.8
    assert metrics[key]["type"] == "gauge"


def test_counter_metric():
    """Test counter metric increments."""
    collector = DefaultMetricsCollector(hostname="test", process_id=1)

    collector.increment("requests.count")
    collector.increment("requests.count", 5)
    collector.increment("requests.count", 3)

    metrics = collector.get_metrics()
    key = list(metrics.keys())[0]

    assert metrics[key]["value"] == 9  # 1 + 5 + 3
    assert metrics[key]["type"] == "counter"


def test_histogram_metric():
    """Test histogram metric collection."""
    collector = DefaultMetricsCollector(hostname="test", process_id=1)

    collector.histogram("response.time", 100)
    collector.histogram("response.time", 150)
    collector.histogram("response.time", 200)

    metrics = collector.get_metrics()
    key = list(metrics.keys())[0]

    assert metrics[key]["values"] == [100, 150, 200]
    assert metrics[key]["type"] == "histogram"


def test_timing_metric():
    """Test timing metric (histogram alias)."""
    collector = DefaultMetricsCollector(hostname="test", process_id=1)

    collector.timing("api.latency", 45.5)
    collector.timing("api.latency", 67.8)

    metrics = collector.get_metrics()
    # Timing adds .timing suffix
    key = list(metrics.keys())[0]

    assert "api.latency.timing" in key
    assert metrics[key]["type"] == "histogram"
    assert metrics[key]["values"] == [45.5, 67.8]


def test_multiple_metrics_with_different_tags():
    """Test that metrics with different tags are stored separately."""
    collector = DefaultMetricsCollector(hostname="test", process_id=1)

    collector.gauge("connections", 10, {"protocol": "http"})
    collector.gauge("connections", 5, {"protocol": "https"})
    collector.gauge("connections", 3, {"protocol": "ws"})

    metrics = collector.get_metrics()
    assert len(metrics) == 3  # Different tags = different metrics

    # Check values
    values = {m["tags"]["protocol"]: m["value"] for m in metrics.values()}
    assert values["http"] == 10
    assert values["https"] == 5
    assert values["ws"] == 3


def test_clear_metrics():
    """Test clearing all metrics."""
    collector = DefaultMetricsCollector(hostname="test", process_id=1)

    collector.gauge("test1", 1)
    collector.increment("test2", 2)
    collector.histogram("test3", 3)

    assert len(collector.get_metrics()) == 3

    collector.clear()
    assert len(collector.get_metrics()) == 0
