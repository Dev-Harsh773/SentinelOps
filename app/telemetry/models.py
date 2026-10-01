"""Telemetry and evidence domain models for SentinelOps."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class EvidenceType(str, Enum):
    """Classification of collected evidence."""

    RUNTIME_LOG = "runtime_log"
    HEALTH_CHECK = "health_check"


@dataclass
class Evidence:
    """Core domain model representing a verified piece of runtime incident evidence."""

    id: str
    incident_id: str
    type: EvidenceType
    source: str
    timestamp: datetime
    service: str
    level: str
    event: str
    message: str
    endpoint: Optional[str]
    exception_type: Optional[str]
    created_at: datetime
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Deterministic fingerprint representing stable source-event identity for deduplication.

        Combines incident_id, source, request_id, trace_id, event, timestamp, and exception_type.
        Kept internal to prevent duplicate ingestion of identical runtime events.
        """
        ts_iso = self.timestamp.isoformat()
        exc_str = self.exception_type or ""
        req_str = self.request_id or ""
        trace_str = self.trace_id or ""
        return f"{self.incident_id}|{self.source}|{req_str}|{trace_str}|{self.event}|{ts_iso}|{exc_str}"

