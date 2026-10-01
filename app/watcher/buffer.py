"""In-memory rolling bounded telemetry buffer for Sentinel Watcher.

Maintains a bounded collection of recent TelemetryEvent instances in memory
using collections.deque with maxlen, enforcing O(1) FIFO eviction upon overflow.
Designed for single-process asyncio execution without blocking I/O during mutation.
"""

from collections import deque
from datetime import datetime
from typing import List, Optional

from app.watcher.models import SignalType, TelemetryEvent


class RollingTelemetryBuffer:
    """Bounded in-memory ring buffer for low-latency queries on recent telemetry."""

    def __init__(self, capacity: int = 1000) -> None:
        if capacity <= 0:
            raise ValueError("Buffer capacity must be a positive integer")
        self._capacity = capacity
        self._deque: deque[TelemetryEvent] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        """Maximum number of events held in memory."""
        return self._capacity

    def size(self) -> int:
        """Current number of events held in buffer."""
        return len(self._deque)

    def append(self, event: TelemetryEvent) -> None:
        """Add a telemetry event to the buffer.

        When capacity is reached, the oldest event is automatically discarded.
        """
        self._deque.append(event)

    def get_recent(
        self,
        limit: int = 50,
        signal_type: Optional[SignalType] = None,
        level: Optional[str] = None,
        service: Optional[str] = None,
        project_id: Optional[str] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[TelemetryEvent]:
        """Return matching events in reverse chronological order (newest first)."""
        results: List[TelemetryEvent] = []
        target_level = level.upper() if level else None

        # Iterate from newest to oldest
        for event in reversed(self._deque):
            if signal_type and event.signal_type != signal_type:
                continue
            if target_level and event.level != target_level:
                continue
            if service and event.service != service:
                continue
            if project_id and event.project_id != project_id:
                continue
            if request_id and event.request_id != request_id:
                continue
            if trace_id and event.trace_id != trace_id:
                continue
            if endpoint and event.endpoint != endpoint:
                continue
            if start_time and event.timestamp < start_time:
                continue
            if end_time and event.timestamp > end_time:
                continue

            results.append(event)
            if len(results) >= limit:
                break

        return results

    def clear(self) -> None:
        """Reset the buffer. Reserved for test isolation."""
        self._deque.clear()
