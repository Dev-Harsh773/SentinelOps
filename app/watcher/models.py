"""Domain models for SentinelOps Watcher and Telemetry stream events.

Defines the normalized TelemetryEvent model, collector status contracts,
and watcher operational health structures.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class SignalType(str, Enum):
    """Classification of telemetry signals ingested into SentinelOps."""

    LOG = "log"
    HEALTH = "health"
    METRIC = "metric"
    TRACE = "trace"
    DEPLOYMENT = "deployment"
    CONTAINER = "container"
    INFRASTRUCTURE = "infrastructure"
    SECURITY = "security"
    CUSTOM = "custom"


class CollectorStatus(str, Enum):
    """Operational status of a background telemetry collector."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    STOPPED = "stopped"


class CollectorType(str, Enum):
    """Type of telemetry collector."""

    FILE = "file"
    HEALTH_CHECK = "health_check"


class WatcherStatus(str, Enum):
    """High-level status of the Sentinel Watcher subsystem."""

    RUNNING = "running"
    STOPPED = "stopped"
    DEGRADED = "degraded"


@dataclass
class CollectorHealth:
    """Diagnostic health summary for an individual collector."""

    name: str
    collector_type: CollectorType
    status: CollectorStatus
    last_event_at: Optional[datetime] = None
    total_events_collected: int = 0
    error_count: int = 0
    last_error: Optional[str] = None


@dataclass(frozen=True)
class TelemetryEvent:
    """Normalized, immutable runtime telemetry event.

    Represents a single continuous operational signal emitted by a monitored service
    or synthetic health observer before any incident declaration.
    """

    event_id: str
    project_id: str
    service: str
    environment: str
    signal_type: SignalType
    source: str
    timestamp: datetime
    ingested_at: datetime
    level: str
    event_type: str
    message: str
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    endpoint: Optional[str] = None
    status_code: Optional[int] = None
    exception_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
