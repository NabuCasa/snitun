"""Base metrics collector interface."""

from abc import ABC, abstractmethod


class MetricsCollector(ABC):
    """Abstract base class for metrics collection."""

    @abstractmethod
    def gauge(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        Set a gauge metric to a specific value.

        Args:
            name: Metric name (e.g., 'snitun.peer.connections')
            value: Current value
            tags: Optional tags for the metric
        """

    @abstractmethod
    def increment(
        self,
        name: str,
        value: float = 1,
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        Increment a counter metric.

        Args:
            name: Metric name (e.g., 'snitun.connections.new')
            value: Amount to increment (default: 1)
            tags: Optional tags for the metric
        """

    @abstractmethod
    def histogram(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        Record a value in a histogram.

        Args:
            name: Metric name (e.g., 'snitun.connection.duration')
            value: Value to record
            tags: Optional tags for the metric
        """

    @abstractmethod
    def timing(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        Record a timing value.

        Args:
            name: Metric name (e.g., 'snitun.handshake.time')
            value: Time in milliseconds
            tags: Optional tags for the metric
        """
