"""Domain models and enumerated types for SentinelOps Operational Reports."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class TimelineEventType(str, Enum):
    """Categorized timeline events derived strictly from recorded system artifacts."""

    INCIDENT_CREATED = "incident_created"
    EVIDENCE_INGESTED = "evidence_ingested"
    INVESTIGATION_STARTED = "investigation_started"
    INVESTIGATION_COMPLETED = "investigation_completed"
    INVESTIGATION_FAILED = "investigation_failed"
    REMEDIATION_PROPOSED = "remediation_proposed"
    REMEDIATION_REVIEWED = "remediation_reviewed"
    SAFE_ACTION_PROPOSED = "safe_action_proposed"
    SAFE_ACTION_POLICY_DENIED = "safe_action_policy_denied"
    SAFE_ACTION_APPROVED = "safe_action_approved"
    SAFE_ACTION_REJECTED = "safe_action_rejected"
    SAFE_ACTION_EXECUTION_STARTED = "safe_action_execution_started"
    SAFE_ACTION_EXECUTION_COMPLETED = "safe_action_execution_completed"
    SAFE_ACTION_EXECUTION_FAILED = "safe_action_execution_failed"
    SAFE_ACTION_ABORTED = "safe_action_aborted"
    NOTIFICATION_DELIVERED = "notification_delivered"
    NOTIFICATION_FAILED = "notification_failed"


@dataclass
class TimelineEvent:
    """Discrete factual event representing a milestone in the incident lifecycle."""

    timestamp: datetime
    event_type: TimelineEventType
    title: str
    description: str
    source: str
    actor: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
