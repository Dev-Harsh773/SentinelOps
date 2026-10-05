"""API response schemas for SentinelOps Incident Reports and Timelines."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.actions.models import ActionType, ApprovalStatus, ExecutionStatus, PolicyStatus, RiskLevel, TargetType
from app.incidents.models import IncidentStatus, Severity
from app.notifications.models import DeliveryStatus, NotificationChannel, NotificationType
from app.reports.models import TimelineEventType


class TimelineEventSchema(BaseModel):
    """Pydantic schema representing a single chronologically ordered timeline event."""

    timestamp: datetime
    event_type: TimelineEventType
    title: str
    description: str
    source: str
    actor: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IncidentOverviewSection(BaseModel):
    """High-level incident identity, lifecycle state, and duration."""

    incident_id: str
    project_id: str
    title: str
    summary: str
    severity: Severity
    status: IncidentStatus
    service: str
    environment: str
    created_at: datetime
    updated_at: datetime
    duration_seconds: Optional[float] = None


class EvidenceSummaryItem(BaseModel):
    """Summarized factual runtime evidence entry."""

    id: str
    type: str
    source: str
    timestamp: datetime
    level: str
    event: str
    message: str
    endpoint: Optional[str] = None
    exception_type: Optional[str] = None
    request_id: Optional[str] = None


class DetectionAndEvidenceSection(BaseModel):
    """Summary of runtime evidence captured for the incident."""

    total_evidence_count: int
    first_evidence_at: Optional[datetime] = None
    last_evidence_at: Optional[datetime] = None
    items: List[EvidenceSummaryItem] = Field(default_factory=list)


class InvestigationSection(BaseModel):
    """AI investigation findings, root cause analysis, and grounding validations."""

    investigation_id: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failure_location: Optional[str] = None
    triggering_condition: Optional[str] = None
    root_cause_hypothesis: Optional[str] = None
    summary: Optional[str] = None
    confidence: Optional[float] = None
    uncertainties: List[str] = Field(default_factory=list)
    is_valid: Optional[bool] = None
    validation_issues: List[str] = Field(default_factory=list)
    relevant_files: List[str] = Field(default_factory=list)
    relevant_symbols: List[str] = Field(default_factory=list)


class ProposedChangeSummary(BaseModel):
    """Summary of a proposed code modification."""

    file_path: str
    change_type: str
    description: str
    reason: str
    symbol: Optional[str] = None


class RemediationSection(BaseModel):
    """Evidence-grounded code remediation proposal and isolated branch details."""

    remediation_id: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    rationale: Optional[str] = None
    risks: List[str] = Field(default_factory=list)
    validation_steps: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    proposed_changes: List[ProposedChangeSummary] = Field(default_factory=list)
    branch_name: Optional[str] = None
    base_commit: Optional[str] = None


class HumanDecisionItem(BaseModel):
    """Auditable record of an operator decision (remediation review or safe action approval/rejection)."""

    decision_type: str  # "remediation_review", "safe_action_approval", "safe_action_rejection"
    decision: str
    actor: str
    comment_or_reason: Optional[str] = None
    timestamp: datetime
    target_id: Optional[str] = None


class SafeActionReportItem(BaseModel):
    """Executed or proposed operational Safe Action details and outcome."""

    action_id: str
    action_type: ActionType
    target_type: TargetType
    target_id: str
    risk_level: RiskLevel
    policy_status: PolicyStatus
    policy_denial_reason: Optional[str] = None
    approval_status: ApprovalStatus
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    execution_status: ExecutionStatus
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_result: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None
    created_at: datetime


class NotificationReportItem(BaseModel):
    """Dispatched or attempted notification status."""

    notification_id: str
    channel: NotificationChannel
    recipient: str
    title: str
    notification_type: NotificationType
    delivery_status: DeliveryStatus
    attempt_count: int
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    created_at: datetime


class SimilarIncidentReportItem(BaseModel):
    """Historical incident memory matched deterministically via Stage 7 matcher."""

    incident_id: str
    project_id: str
    title: str
    service: str
    severity: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    similarity_score: float
    matched_signals: List[str] = Field(default_factory=list)
    failure_location: str
    triggering_condition: str
    root_cause_hypothesis: str
    resolution_notes: Optional[str] = None


class IncidentReportResponse(BaseModel):
    """Complete on-demand read-only incident report read model."""

    incident: IncidentOverviewSection
    detection_and_evidence: DetectionAndEvidenceSection
    investigation: Optional[InvestigationSection] = None
    remediation: Optional[RemediationSection] = None
    human_decisions: List[HumanDecisionItem] = Field(default_factory=list)
    safe_actions: List[SafeActionReportItem] = Field(default_factory=list)
    notifications: List[NotificationReportItem] = Field(default_factory=list)
    similar_incidents: List[SimilarIncidentReportItem] = Field(default_factory=list)
    timeline: List[TimelineEventSchema] = Field(default_factory=list)
    generated_at: datetime
