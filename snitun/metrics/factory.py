"""Factory functions for creating metrics collectors."""

from collections.abc import Callable

from .base import MetricsCollector
from .noop import NoOpMetricsCollector

# Type alias for metrics factory function
MetricsFactory = Callable[[], MetricsCollector]


def create_noop_metrics_collector() -> MetricsCollector:
    """
    Create a no-op metrics collector for zero overhead.

    Returns:
        NoOpMetricsCollector instance that does nothing.
    """
    return NoOpMetricsCollector()
