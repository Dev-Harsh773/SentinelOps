"""Unit tests for desktop DTO deserialization and schema alignment."""

from datetime import datetime, timezone
from desktop.api.models import (
    ConfigFileInfoDTO,
    ConnectorDTO,
    ConnectorHealthDTO,
    DetectedRouteDTO,
    EvidenceDTO,
    EvidenceReferenceDTO,
    IncidentDTO,
    InvestigationDTO,
    NotificationDTO,
    ProjectDTO,
    ProjectKnowledgeDTO,
    ProposedChangeDTO,
    RemediationBranchDTO,
    RemediationDTO,
    RemediationReviewDTO,
    RootCauseAnalysisDTO,
    RuntimeAnalysisDTO,
    WatcherStatusDTO,
)


def test_project_dto_from_dict():
    raw = {
        "project_id": "proj-1",
        "name": "Project Alpha",
        "workspace_path": "D:/repos/alpha",
        "status": "ready",
        "created_at": "2026-10-02T12:00:00Z",
        "indexed_at": "2026-10-02T12:05:00Z",
    }
    dto = ProjectDTO.from_dict(raw)
    assert dto.project_id == "proj-1"
    assert dto.name == "Project Alpha"
    assert dto.workspace_path == "D:/repos/alpha"
    assert dto.status == "ready"
    assert dto.created_at is not None
    assert dto.indexed_at is not None


def test_project_knowledge_dto_from_dict():
    raw = {
        "project_id": "proj-1",
        "index_version": "1.0",
        "indexed_at": "2026-10-02T12:00:00Z",
        "files_count": 42,
        "chunks_count": 180,
        "routes": [
            {
                "method": "POST",
                "path": "/api/orders",
                "file_path": "app/routes.py",
                "function_name": "create_order",
                "start_line": 25,
            }
        ],
        "config_files": [
            {"file_name": "pyproject.toml", "rel_path": "pyproject.toml", "size_bytes": 512}
        ],
        "is_git": True,
        "current_head": "abcdef123456",
        "current_branch": "main",
    }
    dto = ProjectKnowledgeDTO.from_dict(raw)
    assert dto.project_id == "proj-1"
    assert dto.files_count == 42
    assert dto.chunks_count == 180
    assert len(dto.routes) == 1
    assert dto.routes[0].method == "POST"
    assert dto.routes[0].path == "/api/orders"
    assert len(dto.config_files) == 1
    assert dto.config_files[0].file_name == "pyproject.toml"
    assert dto.is_git is True
    assert dto.current_head == "abcdef123456"
    assert dto.current_branch == "main"


def test_incident_dto_from_dict():
    raw = {
        "id": "inc-100",
        "title": "Database Connection Timeout",
        "summary": "Connection pool exhausted under load",
        "severity": "critical",
        "status": "open",
        "service": "order-service",
        "environment": "production",
        "created_at": "2026-10-02T14:00:00Z",
        "updated_at": "2026-10-02T14:05:00Z",
        "project_id": "proj-1",
    }
    dto = IncidentDTO.from_dict(raw)
    assert dto.id == "inc-100"
    assert dto.title == "Database Connection Timeout"
    assert dto.severity == "critical"
    assert dto.status == "open"
    assert dto.project_id == "proj-1"


def test_investigation_dto_from_dict():
    raw = {
        "incident_id": "inc-100",
        "status": "completed",
        "created_at": "2026-10-02T14:01:00Z",
        "completed_at": "2026-10-02T14:02:00Z",
        "rca": {
            "failure_location": "db/pool.py:acquire",
            "triggering_condition": "active_connections >= max_pool_size",
            "root_cause_hypothesis": "Leaked connections during retry loop",
            "summary": "Pool exhaustion due to unclosed sessions",
            "supporting_evidence": [
                {"type": "runtime", "id": "ev-1", "description": "ConnectionTimeout in logs"}
            ],
            "contradicting_evidence": [],
            "confidence": 0.88,
            "uncertainties": ["Database server side metric missing"],
        },
        "errors": [],
    }
    dto = InvestigationDTO.from_dict(raw)
    assert dto.incident_id == "inc-100"
    assert dto.status == "completed"
    assert dto.rca is not None
    assert dto.rca.failure_location == "db/pool.py:acquire"
    assert dto.rca.confidence == 0.88
    assert len(dto.rca.supporting_evidence) == 1
    assert dto.rca.supporting_evidence[0].id == "ev-1"


def test_remediation_dto_from_dict():
    raw = {
        "remediation_id": "rem-100",
        "incident_id": "inc-100",
        "investigation_id": "inv-100",
        "status": "proposed",
        "summary": "Add context manager around session acquire",
        "target_files": ["db/pool.py"],
        "target_symbols": ["acquire_connection"],
        "proposed_changes": [
            {
                "file_path": "db/pool.py",
                "change_type": "modify",
                "description": "Use try/finally to release connection",
                "reason": "Ensure connection is always returned to pool",
                "symbol": "acquire_connection",
            }
        ],
        "rationale": "Prevents leaks during network timeouts",
        "risks": ["Slight overhead"],
        "validation_steps": ["Run pool stress test"],
    }
    dto = RemediationDTO.from_dict(raw)
    assert dto.remediation_id == "rem-100"
    assert len(dto.proposed_changes) == 1
    assert dto.proposed_changes[0].file_path == "db/pool.py"
    assert dto.proposed_changes[0].change_type == "modify"


def test_notification_dto_from_dict():
    raw = {
        "notification_id": "notif-1",
        "project_id": "proj-1",
        "incident_id": "inc-100",
        "subscription_id": "sub-1",
        "notification_type": "incident.created",
        "severity": "critical",
        "title": "Incident Created: Database Connection Timeout",
        "message": "Critical incident in production",
        "payload": {"incident_id": "inc-100"},
        "channel": "local_feed",
        "recipient": "local",
        "delivery_status": "delivered",
        "read_status": "unread",
        "attempt_count": 1,
        "created_at": "2026-10-02T14:00:00Z",
        "updated_at": "2026-10-02T14:00:00Z",
    }
    dto = NotificationDTO.from_dict(raw)
    assert dto.notification_id == "notif-1"
    assert dto.project_id == "proj-1"
    assert dto.incident_id == "inc-100"
    assert dto.read_status == "unread"
    assert dto.delivery_status == "delivered"


def test_connector_dto_from_dict():
    raw = {
        "connector_id": "conn-1",
        "project_id": "proj-1",
        "name": "Auth API Poller",
        "connector_type": "http_poller",
        "config": {"url": "https://auth.internal/health"},
        "status": "active",
        "created_at": "2026-10-02T10:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "health": {
            "connector_id": "conn-1",
            "operational_status": "healthy",
            "target_status": "healthy",
            "last_poll_at": "2026-10-02T14:00:00Z",
            "consecutive_operational_errors": 0,
        },
    }
    dto = ConnectorDTO.from_dict(raw)
    assert dto.connector_id == "conn-1"
    assert dto.name == "Auth API Poller"
    assert dto.health is not None
    assert dto.health.operational_status == "healthy"
    assert dto.health.target_status == "healthy"
    assert dto.health.consecutive_operational_errors == 0


def test_watcher_status_dto_from_dict():
    raw = {
        "watcher_status": "running",
        "enabled": True,
        "uptime_seconds": 1234.5,
        "buffer": {"count": 150, "capacity": 1000},
        "storage": {},
        "collectors": {},
    }
    dto = WatcherStatusDTO.from_dict(raw)
    assert dto.watcher_status == "running"
    assert dto.enabled is True
    assert dto.buffer_count == 150
    assert dto.buffer_capacity == 1000
