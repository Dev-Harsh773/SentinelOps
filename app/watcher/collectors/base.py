"""Base collector protocol and contract for Sentinel Watcher observers."""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from app.watcher.models import CollectorHealth, CollectorType, TelemetryEvent


class TelemetryCollector(ABC):
    """Abstract contract for active background telemetry observers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier name for this collector instance."""
        pass

    @property
    @abstractmethod
    def collector_type(self) -> CollectorType:
        """Classification of this collector."""
        pass

    @abstractmethod
    async def start(self, emit_callback: Callable[[TelemetryEvent], Awaitable[None]]) -> None:
        """Start collector background observation loop with an async emission callback."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully terminate collector background loop and release open resources."""
        pass

    @abstractmethod
    def health(self) -> CollectorHealth:
        """Return the current diagnostic health summary of this collector."""
        pass
