"""Telemetry and evidence domain models for SentinelOps."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class EvidenceType(str, Enum):
    """Classification of collected evidence."""

    RUNTIME_LOG = "runtime_log"


@dataclass
class Evidence:
    """Core domain model representing a verified piece of runtime incident evidence."""

    id: str
    incident_id: str
    type: EvidenceType
    source: str
    timestamp: datetime
    service: str
    request_id: str
    level: str
    event: str
    message: str
    endpoint: Optional[str]
    exception_type: Optional[str]
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Deterministic fingerprint representing stable source-event identity for deduplication.

        Combines incident_id, source, request_id, event, timestamp, and exception_type.
        Kept internal to prevent duplicate ingestion of identical runtime events.
        """
        ts_iso = self.timestamp.isoformat()
        exc_str = self.exception_type or ""
        return f"{self.incident_id}|{self.source}|{self.request_id}|{self.event}|{ts_iso}|{exc_str}"
