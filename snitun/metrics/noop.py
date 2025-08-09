"""No-operation metrics collector for zero overhead."""

from .base import MetricsCollector


class NoOpMetricsCollector(MetricsCollector):
    """No-operation metrics collector with zero overhead."""

    def gauge(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """No-op gauge implementation."""

    def increment(
        self,
        name: str,
        value: float = 1,
        tags: dict[str, str] | None = None,
    ) -> None:
        """No-op increment implementation."""

    def histogram(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """No-op histogram implementation."""

    def timing(
        self,
        name: str,
        value: float,
        tags: dict[str, str] | None = None,
    ) -> None:
        """No-op timing implementation."""
