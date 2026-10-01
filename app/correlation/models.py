"""Domain models for SentinelOps incident correlation subsystem."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Set


class CorrelationType(str, Enum):
    """Classification of the match mechanism used to correlate telemetry."""

    STRONG_REQUEST_ID = "strong_request_id"
    STRONG_TRACE_ID = "strong_trace_id"
    FALLBACK_ENDPOINT = "fallback_endpoint"
    STAGE11_SUPPRESSION = "stage11_suppression"


@dataclass
class ActiveIncidentCorrelation:
    """State tracking an active incident for bounded telemetry correlation and suppression."""

    correlation_id: str
    incident_id: str
    project_id: str
    service: str
    environment: str
    endpoint: Optional[str]
    request_ids: Set[str]
    trace_ids: Set[str]
    anchor_event_timestamp: datetime
    last_correlated_event_timestamp: datetime
    created_process_time: datetime
    expires_at_process_time: datetime
    evidence_count: int = 1
    suppression_fingerprints: Set[str] = field(default_factory=set)

    def is_expired(self, current_process_time: datetime) -> bool:
        """Evaluate if active post-trigger collection window has elapsed in process time."""
        return current_process_time > self.expires_at_process_time
