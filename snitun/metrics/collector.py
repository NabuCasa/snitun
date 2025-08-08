"""Default in-memory metrics collector implementation."""

from datetime import UTC, datetime
import os
import socket
from typing import Any

from .base import MetricsCollector


class DefaultMetricsCollector(MetricsCollector):
    """
    Default in-memory metrics collector with automatic system tagging.

    This collector stores metrics in memory for debugging and testing.
    It automatically adds hostname and process_id tags to all metrics.
    Does not need to be thread-safe as it runs in a single event loop.
    """

    def __init__(
        self,
        hostname: str | None = None,
        process_id: int | None = None,
    ) -> None:
        """
        Initialize the collector.

        Args:
            hostname: Override system hostname (default: socket.gethostname())
            process_id: Override process ID (default: os.getpid())
        """
        self._hostname = hostname or socket.gethostname()
        self._process_id = process_id or os.getpid()
        self._metrics: dict[str, Any] = {}
        self._start_time = datetime.now(tz=UTC)

    def _add_system_tags(self, tags: dict[str, str] | None) -> dict[str, str]:
        """Add hostname and process_id to all metrics."""
        final_tags = tags.copy() if tags else {}
        # System tags override any user-provided tags with the same name
        final_tags["hostname"] = self._hostname
        final_tags["process_id"] = str(self._process_id)
        return final_tags

    def _make_key(self, name: str, tags: dict[str, str]) -> str:
        """Create a unique key for the metric."""
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name},{tag_str}"

    def gauge(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge value."""
        tags = self._add_system_tags(tags)
        key = self._make_key(name, tags)
        self._metrics[key] = {
            "type": "gauge",
            "name": name,
            "value": value,
            "timestamp": datetime.now(tz=UTC),
            "tags": tags,
        }

    def increment(
        self,
        name: str,
        value: float = 1,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter."""
        tags = self._add_system_tags(tags)
        key = self._make_key(name, tags)

        if key not in self._metrics or self._metrics[key]["type"] != "counter":
            self._metrics[key] = {
                "type": "counter",
                "name": name,
                "value": 0,
                "tags": tags,
            }

        self._metrics[key]["value"] += value
        self._metrics[key]["timestamp"] = datetime.now(tz=UTC)

    def histogram(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Record a histogram value."""
        tags = self._add_system_tags(tags)
        key = self._make_key(name, tags)

        if key not in self._metrics or self._metrics[key]["type"] != "histogram":
            self._metrics[key] = {
                "type": "histogram",
                "name": name,
                "values": [],
                "tags": tags,
            }

        self._metrics[key]["values"].append(value)
        self._metrics[key]["timestamp"] = datetime.now(tz=UTC)

    def timing(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """Record a timing value."""
        # Timing is essentially a histogram with millisecond values
        self.histogram(f"{name}.timing", value, tags)

    def get_metrics(self) -> dict[str, Any]:
        """
        Get all collected metrics.

        Returns:
            Dictionary of all metrics collected so far.
        """
        return self._metrics.copy()

    def clear(self) -> None:
        """Clear all collected metrics."""
        self._metrics.clear()
