"""Domain models for SentinelOps detection engine."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from app.incidents.models import Severity


class DetectionAction(str, Enum):
    """Action taken by the detection engine following rule evaluation."""

    INCIDENT_CREATED = "incident_created"
    SUPPRESSED = "suppressed"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class RuleMatch:
    """Output produced when a TelemetryEvent matches a DetectionRule."""

    rule_id: str
    rule_name: str
    title: str
    summary: str
    severity: Severity
    failure_signature: str


@dataclass(frozen=True)
class DetectionResult:
    """Diagnostic record of a single TelemetryEvent detection evaluation."""

    evaluated_at: datetime
    event_id: str
    project_id: str
    matched: bool
    rule_id: Optional[str] = None
    action: DetectionAction = DetectionAction.NO_MATCH
    incident_id: Optional[str] = None
    suppression_reason: Optional[str] = None
