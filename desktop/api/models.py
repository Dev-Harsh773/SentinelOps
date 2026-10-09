"""Desktop-local Data Transfer Objects (DTOs).

Mirrors verified backend response schemas 1:1 without importing from app.*.
All fields strictly match backend models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def _parse_datetime(val: Any) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class ProjectDTO:
    project_id: str
    name: str
    workspace_path: str
    status: str
    created_at: Optional[datetime] = None
    indexed_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectDTO":
        return cls(
            project_id=str(data.get("project_id", "")),
            name=str(data.get("name", "")),
            workspace_path=str(data.get("workspace_path", "")),
            status=str(data.get("status", "ready")),
            created_at=_parse_datetime(data.get("created_at")),
            indexed_at=_parse_datetime(data.get("indexed_at")),
        )


@dataclass(frozen=True)
class DetectedRouteDTO:
    method: str
    path: str
    file_path: str
    function_name: str
    start_line: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DetectedRouteDTO":
        return cls(
            method=str(data.get("method", "GET")),
            path=str(data.get("path", "")),
            file_path=str(data.get("file_path", "")),
            function_name=str(data.get("function_name", "")),
            start_line=int(data.get("start_line", 1)),
        )


@dataclass(frozen=True)
class ConfigFileInfoDTO:
    file_name: str
    rel_path: str
    size_bytes: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfigFileInfoDTO":
        return cls(
            file_name=str(data.get("file_name", "")),
            rel_path=str(data.get("rel_path", "")),
            size_bytes=int(data.get("size_bytes", 0)),
        )


@dataclass
class ProjectKnowledgeDTO:
    project_id: str
    index_version: str
    indexed_at: Optional[datetime] = None
    files_count: int = 0
    chunks_count: int = 0
    routes: List[DetectedRouteDTO] = field(default_factory=list)
    config_files: List[ConfigFileInfoDTO] = field(default_factory=list)
    is_git: bool = False
    current_head: Optional[str] = None
    current_branch: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectKnowledgeDTO":
        return cls(
            project_id=str(data.get("project_id", "")),
            index_version=str(data.get("index_version", "1.0")),
            indexed_at=_parse_datetime(data.get("indexed_at")),
            files_count=int(data.get("files_count", 0)),
            chunks_count=int(data.get("chunks_count", 0)),
            routes=[DetectedRouteDTO.from_dict(r) for r in data.get("routes", [])],
            config_files=[ConfigFileInfoDTO.from_dict(c) for c in data.get("config_files", [])],
            is_git=bool(data.get("is_git", False)),
            current_head=data.get("current_head"),
            current_branch=data.get("current_branch"),
        )


@dataclass
class IncidentDTO:
    id: str
    title: str
    summary: str
    severity: str
    status: str
    service: str
    environment: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    project_id: str = "default"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IncidentDTO":
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            summary=str(data.get("summary", "")),
            severity=str(data.get("severity", "medium")),
            status=str(data.get("status", "open")),
            service=str(data.get("service", "")),
            environment=str(data.get("environment", "")),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            project_id=str(data.get("project_id", "default")),
        )


@dataclass
class EvidenceDTO:
    evidence_id: str
    incident_id: str
    signal_type: str
    timestamp: Optional[datetime] = None
    log_level: str = "INFO"
    message: str = ""
    source_file: str = ""
    request_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceDTO":
        return cls(
            evidence_id=str(data.get("evidence_id", "")),
            incident_id=str(data.get("incident_id", "")),
            signal_type=str(data.get("signal_type", "LOG")),
            timestamp=_parse_datetime(data.get("timestamp")),
            log_level=str(data.get("log_level", "INFO")),
            message=str(data.get("message", "")),
            source_file=str(data.get("source_file", "")),
            request_id=data.get("request_id"),
            attributes=dict(data.get("attributes", {})),
        )


@dataclass
class EvidenceReferenceDTO:
    type: str
    id: str
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceReferenceDTO":
        return cls(
            type=str(data.get("type", "")),
            id=str(data.get("id", "")),
            description=data.get("description"),
        )


@dataclass
class RootCauseAnalysisDTO:
    failure_location: str
    triggering_condition: str
    root_cause_hypothesis: str
    summary: str
    supporting_evidence: List[EvidenceReferenceDTO] = field(default_factory=list)
    contradicting_evidence: List[EvidenceReferenceDTO] = field(default_factory=list)
    confidence: float = 0.0
    uncertainties: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RootCauseAnalysisDTO":
        return cls(
            failure_location=str(data.get("failure_location", "")),
            triggering_condition=str(data.get("triggering_condition", "")),
            root_cause_hypothesis=str(data.get("root_cause_hypothesis", "")),
            summary=str(data.get("summary", "")),
            supporting_evidence=[EvidenceReferenceDTO.from_dict(e) for e in data.get("supporting_evidence", [])],
            contradicting_evidence=[EvidenceReferenceDTO.from_dict(e) for e in data.get("contradicting_evidence", [])],
            confidence=float(data.get("confidence", 0.0)),
            uncertainties=[str(u) for u in data.get("uncertainties", [])],
        )


@dataclass
class RuntimeAnalysisDTO:
    observed_failures: List[str] = field(default_factory=list)
    service: str = ""
    endpoint: Optional[str] = None
    exception_type: Optional[str] = None
    important_messages: List[str] = field(default_factory=list)
    request_ids: List[str] = field(default_factory=list)
    timeline: List[str] = field(default_factory=list)
    initial_hypotheses: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeAnalysisDTO":
        return cls(
            observed_failures=[str(f) for f in data.get("observed_failures", [])],
            service=str(data.get("service", "")),
            endpoint=data.get("endpoint"),
            exception_type=data.get("exception_type"),
            important_messages=[str(m) for m in data.get("important_messages", [])],
            request_ids=[str(r) for r in data.get("request_ids", [])],
            timeline=[str(t) for t in data.get("timeline", [])],
            initial_hypotheses=[str(h) for h in data.get("initial_hypotheses", [])],
            missing_information=[str(m) for m in data.get("missing_information", [])],
        )


@dataclass
class CodeAnalysisDTO:
    relevant_symbols: List[str] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    code_observations: List[str] = field(default_factory=list)
    possible_relationship_to_failure: List[str] = field(default_factory=list)
    missing_code_context: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeAnalysisDTO":
        return cls(
            relevant_symbols=[str(s) for s in data.get("relevant_symbols", [])],
            relevant_files=[str(f) for f in data.get("relevant_files", [])],
            code_observations=[str(o) for o in data.get("code_observations", [])],
            possible_relationship_to_failure=[str(p) for p in data.get("possible_relationship_to_failure", [])],
            missing_code_context=[str(m) for m in data.get("missing_code_context", [])],
        )


@dataclass
class InvestigationDTO:
    incident_id: str
    status: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    runtime_analysis: Optional[RuntimeAnalysisDTO] = None
    code_analysis: Optional[CodeAnalysisDTO] = None
    rca: Optional[RootCauseAnalysisDTO] = None
    errors: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InvestigationDTO":
        ra = RuntimeAnalysisDTO.from_dict(data["runtime_analysis"]) if data.get("runtime_analysis") else None
        ca = CodeAnalysisDTO.from_dict(data["code_analysis"]) if data.get("code_analysis") else None
        rca = RootCauseAnalysisDTO.from_dict(data["rca"]) if data.get("rca") else None
        return cls(
            incident_id=str(data.get("incident_id", "")),
            status=str(data.get("status", "unknown")),
            created_at=_parse_datetime(data.get("created_at")),
            completed_at=_parse_datetime(data.get("completed_at")),
            runtime_analysis=ra,
            code_analysis=ca,
            rca=rca,
            errors=[str(e) for e in data.get("errors", [])],
        )


@dataclass
class ProposedChangeDTO:
    file_path: str
    change_type: str
    description: str
    reason: str
    symbol: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProposedChangeDTO":
        return cls(
            file_path=str(data.get("file_path", "")),
            change_type=str(data.get("change_type", "modify")),
            description=str(data.get("description", "")),
            reason=str(data.get("reason", "")),
            symbol=data.get("symbol"),
        )


@dataclass
class RemediationDTO:
    remediation_id: str
    incident_id: str
    investigation_id: str
    status: str
    summary: str
    target_files: List[str] = field(default_factory=list)
    target_symbols: List[str] = field(default_factory=list)
    proposed_changes: List[ProposedChangeDTO] = field(default_factory=list)
    rationale: str = ""
    risks: List[str] = field(default_factory=list)
    validation_steps: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemediationDTO":
        return cls(
            remediation_id=str(data.get("remediation_id", "")),
            incident_id=str(data.get("incident_id", "")),
            investigation_id=str(data.get("investigation_id", "")),
            status=str(data.get("status", "proposed")),
            summary=str(data.get("summary", "")),
            target_files=[str(f) for f in data.get("target_files", [])],
            target_symbols=[str(s) for s in data.get("target_symbols", [])],
            proposed_changes=[ProposedChangeDTO.from_dict(p) for p in data.get("proposed_changes", [])],
            rationale=str(data.get("rationale", "")),
            risks=[str(r) for r in data.get("risks", [])],
            validation_steps=[str(v) for v in data.get("validation_steps", [])],
        )


@dataclass
class RemediationReviewDTO:
    review_id: str
    incident_id: str
    remediation_id: str
    decision: str
    reviewer: str
    comment: Optional[str] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemediationReviewDTO":
        return cls(
            review_id=str(data.get("review_id", "")),
            incident_id=str(data.get("incident_id", "")),
            remediation_id=str(data.get("remediation_id", "")),
            decision=str(data.get("decision", "pending")),
            reviewer=str(data.get("reviewer", "")),
            comment=data.get("comment"),
            created_at=_parse_datetime(data.get("created_at")),
        )


@dataclass
class RemediationBranchDTO:
    branch_id: str
    incident_id: str
    remediation_id: str
    approval_id: str
    branch_name: str
    base_branch: str
    base_commit: str
    created_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemediationBranchDTO":
        return cls(
            branch_id=str(data.get("branch_id", "")),
            incident_id=str(data.get("incident_id", "")),
            remediation_id=str(data.get("remediation_id", "")),
            approval_id=str(data.get("approval_id", "")),
            branch_name=str(data.get("branch_name", "")),
            base_branch=str(data.get("base_branch", "")),
            base_commit=str(data.get("base_commit", "")),
            created_at=_parse_datetime(data.get("created_at")),
        )


@dataclass
class NotificationDTO:
    notification_id: str
    project_id: str
    incident_id: Optional[str] = None
    subscription_id: Optional[str] = None
    notification_type: str = "incident.created"
    severity: str = "low"
    title: str = ""
    message: str = ""
    channel: str = "local_feed"
    recipient: str = ""
    delivery_status: str = "delivered"
    read_status: str = "unread"
    attempt_count: int = 0
    next_attempt_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotificationDTO":
        return cls(
            notification_id=str(data.get("notification_id", "")),
            project_id=str(data.get("project_id", "")),
            incident_id=data.get("incident_id"),
            subscription_id=data.get("subscription_id"),
            notification_type=str(data.get("notification_type", "incident.created")),
            severity=str(data.get("severity", "low")),
            title=str(data.get("title", "")),
            message=str(data.get("message", "")),
            channel=str(data.get("channel", "local_feed")),
            recipient=str(data.get("recipient", "")),
            delivery_status=str(data.get("delivery_status", "delivered")),
            read_status=str(data.get("read_status", "unread")),
            attempt_count=int(data.get("attempt_count", 0)),
            next_attempt_at=_parse_datetime(data.get("next_attempt_at")),
            last_attempt_at=_parse_datetime(data.get("last_attempt_at")),
            delivered_at=_parse_datetime(data.get("delivered_at")),
            read_at=_parse_datetime(data.get("read_at")),
            failure_reason=data.get("failure_reason"),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )


@dataclass
class ConnectorHealthDTO:
    connector_id: str
    operational_status: str = "healthy"
    target_status: str = "unknown"
    last_poll_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    consecutive_operational_errors: int = 0
    last_operational_error: Optional[str] = None
    last_target_error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectorHealthDTO":
        return cls(
            connector_id=str(data.get("connector_id", "")),
            operational_status=str(data.get("operational_status", "healthy")),
            target_status=str(data.get("target_status", "unknown")),
            last_poll_at=_parse_datetime(data.get("last_poll_at")),
            last_success_at=_parse_datetime(data.get("last_success_at")),
            consecutive_operational_errors=int(data.get("consecutive_operational_errors", 0)),
            last_operational_error=data.get("last_operational_error"),
            last_target_error=data.get("last_target_error"),
        )


@dataclass
class ConnectorDTO:
    connector_id: str
    project_id: str
    name: str
    connector_type: str
    config: Dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    health: Optional[ConnectorHealthDTO] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectorDTO":
        health = ConnectorHealthDTO.from_dict(data["health"]) if data.get("health") else None
        return cls(
            connector_id=str(data.get("connector_id", "")),
            project_id=str(data.get("project_id", "")),
            name=str(data.get("name", "")),
            connector_type=str(data.get("connector_type", "http_poller")),
            config=dict(data.get("config", {})),
            status=str(data.get("status", "active")),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            health=health,
        )


@dataclass
class WatcherStatusDTO:
    watcher_status: str = "running"
    enabled: bool = True
    uptime_seconds: float = 0.0
    buffer_count: int = 0
    buffer_capacity: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WatcherStatusDTO":
        buf = data.get("buffer", {})
        return cls(
            watcher_status=str(data.get("watcher_status", "running")),
            enabled=bool(data.get("enabled", True)),
            uptime_seconds=float(data.get("uptime_seconds", 0.0)),
            buffer_count=int(buf.get("count", 0)),
            buffer_capacity=int(buf.get("capacity", 0)),
        )


@dataclass
class SafeActionDTO:
    action_id: str
    project_id: str
    incident_id: Optional[str]
    action_type: str
    target_type: str
    target_id: str
    parameters: Dict[str, Any]
    fingerprint: str
    requested_by_claim: str
    risk_level: str
    policy_status: str
    approval_status: str
    execution_status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    policy_denial_reason: Optional[str] = None
    approved_by_claim: Optional[str] = None
    approved_at: Optional[datetime] = None
    approved_fingerprint: Optional[str] = None
    rejection_reason: Optional[str] = None
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_result: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SafeActionDTO":
        return cls(
            action_id=str(data.get("action_id", "")),
            project_id=str(data.get("project_id", "")),
            incident_id=data.get("incident_id"),
            action_type=str(data.get("action_type", "")),
            target_type=str(data.get("target_type", "")),
            target_id=str(data.get("target_id", "")),
            parameters=dict(data.get("parameters", {})),
            fingerprint=str(data.get("fingerprint", "")),
            requested_by_claim=str(data.get("requested_by_claim", "")),
            risk_level=str(data.get("risk_level", "low")),
            policy_status=str(data.get("policy_status", "allowed")),
            approval_status=str(data.get("approval_status", "pending")),
            execution_status=str(data.get("execution_status", "not_started")),
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
            policy_denial_reason=data.get("policy_denial_reason"),
            approved_by_claim=data.get("approved_by_claim"),
            approved_at=_parse_datetime(data.get("approved_at")),
            approved_fingerprint=data.get("approved_fingerprint"),
            rejection_reason=data.get("rejection_reason"),
            executed_at=_parse_datetime(data.get("executed_at")),
            completed_at=_parse_datetime(data.get("completed_at")),
            execution_result=data.get("execution_result"),
            failure_reason=data.get("failure_reason"),
        )


@dataclass
class ActionAuditDTO:
    audit_id: str
    action_id: str
    event_type: str
    actor_claim: str
    previous_state: Dict[str, Any]
    new_state: Dict[str, Any]
    message: str
    payload: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionAuditDTO":
        return cls(
            audit_id=str(data.get("audit_id", "")),
            action_id=str(data.get("action_id", "")),
            event_type=str(data.get("event_type", "")),
            actor_claim=str(data.get("actor_claim", "")),
            previous_state=dict(data.get("previous_state", {})),
            new_state=dict(data.get("new_state", {})),
            message=str(data.get("message", "")),
            payload=data.get("payload"),
            created_at=_parse_datetime(data.get("created_at")),
        )


@dataclass
class TimelineEventDTO:
    timestamp: Optional[datetime]
    event_type: str
    title: str
    description: str
    source: str
    actor: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineEventDTO":
        return cls(
            timestamp=_parse_datetime(data.get("timestamp")),
            event_type=str(data.get("event_type", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            source=str(data.get("source", "")),
            actor=data.get("actor"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SimilarIncidentReportDTO:
    incident_id: str
    project_id: str
    title: str
    service: str
    severity: Optional[str]
    status: Optional[str]
    created_at: Optional[datetime]
    similarity_score: float
    matched_signals: List[str]
    failure_location: str
    triggering_condition: str
    root_cause_hypothesis: str
    resolution_notes: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimilarIncidentReportDTO":
        return cls(
            incident_id=str(data.get("incident_id", "")),
            project_id=str(data.get("project_id", "")),
            title=str(data.get("title", "")),
            service=str(data.get("service", "")),
            severity=data.get("severity"),
            status=data.get("status"),
            created_at=_parse_datetime(data.get("created_at")),
            similarity_score=float(data.get("similarity_score", 0.0)),
            matched_signals=list(data.get("matched_signals", [])),
            failure_location=str(data.get("failure_location", "")),
            triggering_condition=str(data.get("triggering_condition", "")),
            root_cause_hypothesis=str(data.get("root_cause_hypothesis", "")),
            resolution_notes=data.get("resolution_notes"),
        )


@dataclass
class IncidentReportDTO:
    incident: Dict[str, Any]
    detection_and_evidence: Dict[str, Any]
    investigation: Optional[Dict[str, Any]]
    remediation: Optional[Dict[str, Any]]
    human_decisions: List[Dict[str, Any]]
    safe_actions: List[Dict[str, Any]]
    notifications: List[Dict[str, Any]]
    similar_incidents: List[SimilarIncidentReportDTO]
    timeline: List[TimelineEventDTO]
    generated_at: Optional[datetime]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IncidentReportDTO":
        sims = [SimilarIncidentReportDTO.from_dict(d) for d in data.get("similar_incidents", [])]
        events = [TimelineEventDTO.from_dict(d) for d in data.get("timeline", [])]
        return cls(
            incident=dict(data.get("incident", {})),
            detection_and_evidence=dict(data.get("detection_and_evidence", {})),
            investigation=data.get("investigation"),
            remediation=data.get("remediation"),
            human_decisions=list(data.get("human_decisions", [])),
            safe_actions=list(data.get("safe_actions", [])),
            notifications=list(data.get("notifications", [])),
            similar_incidents=sims,
            timeline=events,
            generated_at=_parse_datetime(data.get("generated_at")),
        )


@dataclass
class ConnectorCreateDTO(ConnectorDTO):
    raw_auth_secret: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectorCreateDTO":
        base = ConnectorDTO.from_dict(data)
        return cls(
            connector_id=base.connector_id,
            project_id=base.project_id,
            name=base.name,
            connector_type=base.connector_type,
            config=base.config,
            status=base.status,
            created_at=base.created_at,
            updated_at=base.updated_at,
            health=base.health,
            raw_auth_secret=data.get("raw_auth_secret"),
        )


@dataclass
class ProjectReadinessDTO:
    project_id: str
    project_status: str
    is_indexed: bool
    source_connected: bool
    connectors_count: int
    active_connectors_count: int
    health_status: Optional[str] = None
    last_telemetry_at: Optional[datetime] = None
    telemetry_receiving: bool = False
    recency_window_seconds: int = 900
    external_webhook_ready: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectReadinessDTO":
        return cls(
            project_id=str(data.get("project_id", "")),
            project_status=str(data.get("project_status", "ready")),
            is_indexed=bool(data.get("is_indexed", False)),
            source_connected=bool(data.get("source_connected", False)),
            connectors_count=int(data.get("connectors_count", 0)),
            active_connectors_count=int(data.get("active_connectors_count", 0)),
            health_status=data.get("health_status"),
            last_telemetry_at=_parse_datetime(data.get("last_telemetry_at")),
            telemetry_receiving=bool(data.get("telemetry_receiving", False)),
            recency_window_seconds=int(data.get("recency_window_seconds", 900)),
            external_webhook_ready=bool(data.get("external_webhook_ready", True)),
        )
