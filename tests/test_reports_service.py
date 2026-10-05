"""Tests for Stage 19 ReportService aggregation, sparse incidents, and project isolation."""

from datetime import datetime, timezone
import pytest

from app.actions.dependencies import close_action_store, get_action_store, set_custom_action_db_path
from app.actions.models import (
    ActionAuditRecord,
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    SafeAction,
    TargetType,
)
from app.agents.dependencies import close_investigation_repository, get_investigation_repository, set_custom_investigation_db_path
from app.agents.models import EvidenceReference, Investigation, InvestigationStatus, RootCauseAnalysis
from app.incidents.dependencies import close_incident_repository, get_incident_repository, set_custom_incident_db_path
from app.incidents.models import Incident, IncidentStatus, Severity
from app.memory.dependencies import close_memory_repository, get_memory_repository, get_memory_service, set_custom_memory_db_path
from app.memory.models import IncidentMemory
from app.notifications.dependencies import close_notification_store, get_notification_store, set_custom_notification_db_path
from app.notifications.models import DeliveryStatus, Notification, NotificationChannel, NotificationType
from app.remediation.dependencies import (
    close_remediation_repositories,
    get_branch_repository,
    get_remediation_repository,
    get_review_repository,
    set_custom_remediation_db_path,
)
from app.remediation.models import RemediationProposal, RemediationReview, RemediationStatus, ReviewDecision
from app.reports.dependencies import get_report_service
from app.reports.service import ProjectIsolationError
from app.telemetry.dependencies import close_evidence_repository, get_evidence_repository, set_custom_evidence_db_path
from app.telemetry.models import Evidence, EvidenceType


@pytest.fixture(autouse=True)
def setup_test_dbs(tmp_path):
    test_db = str(tmp_path / "test_report_service.db")
    set_custom_incident_db_path(test_db)
    set_custom_evidence_db_path(test_db)
    set_custom_investigation_db_path(test_db)
    set_custom_remediation_db_path(test_db)
    set_custom_action_db_path(test_db)
    set_custom_notification_db_path(test_db)
    set_custom_memory_db_path(test_db)

    # Seed projects table for foreign key satisfaction
    action_store = get_action_store()
    with action_store._lock:
        cursor = action_store._conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO projects (
                project_id, name, workspace_path, normalized_path, is_git, status, created_at, updated_at
            ) VALUES ('proj-alpha', 'Alpha Project', '/work', '/work', 1, 'ready', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        action_store._conn.commit()

    yield

    close_remediation_repositories()
    close_investigation_repository()
    close_evidence_repository()
    close_memory_repository()
    close_action_store()
    close_notification_store()
    close_incident_repository()

    set_custom_incident_db_path(None)
    set_custom_evidence_db_path(None)
    set_custom_investigation_db_path(None)
    set_custom_remediation_db_path(None)
    set_custom_action_db_path(None)
    set_custom_notification_db_path(None)
    set_custom_memory_db_path(None)


def test_sparse_incident_report_defaults():
    """Verify fresh minimal incident yields clean None/empty states and zero fabricated data."""
    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    inc = Incident(
        id="inc-sparse",
        title="Sparse Incident",
        summary="Minimal summary",
        severity=Severity.LOW,
        status=IncidentStatus.OPEN,
        service="sparse-svc",
        environment="test",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )
    get_incident_repository().create(inc)

    report_svc = get_report_service()
    report = report_svc.generate_report("inc-sparse", project_id="proj-alpha")

    assert report.incident.incident_id == "inc-sparse"
    assert report.incident.duration_seconds is None  # Active incident duration is None
    assert report.detection_and_evidence.total_evidence_count == 0
    assert report.detection_and_evidence.items == []
    assert report.investigation is None
    assert report.remediation is None
    assert report.human_decisions == []
    assert report.safe_actions == []
    assert report.notifications == []
    assert report.similar_incidents == []
    assert len(report.timeline) == 1
    assert report.timeline[0].title == "Incident Created"


def test_complete_incident_report_aggregation():
    """Verify report accurately aggregates facts from evidence, RCA, remediation, actions, and memory."""
    t0 = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 2, 10, 5, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 2, 10, 15, tzinfo=timezone.utc)

    # 1. Incident
    inc = Incident(
        id="inc-full",
        title="Full Pipeline Incident",
        summary="Full summary",
        severity=Severity.HIGH,
        status=IncidentStatus.RESOLVED,
        service="checkout-svc",
        environment="prod",
        created_at=t0,
        updated_at=t2,
        project_id="proj-alpha",
    )
    get_incident_repository().create(inc)

    # 2. Evidence
    ev = Evidence(
        id="ev-f1",
        incident_id="inc-full",
        type=EvidenceType.RUNTIME_LOG,
        source="runtime.log",
        timestamp=t0,
        service="checkout-svc",
        level="ERROR",
        event="checkout_failed",
        message="Payment timeout",
        endpoint="/checkout",
        exception_type="PaymentGatewayTimeout",
        created_at=t0,
    )
    get_evidence_repository().create(ev)

    # 3. Investigation
    inv = Investigation(
        investigation_id="inv-f1",
        incident_id="inc-full",
        status=InvestigationStatus.COMPLETED,
        created_at=t0,
        completed_at=t1,
        rca=RootCauseAnalysis(
            failure_location="checkout/gateway.py",
            triggering_condition="upstream gateway latency > 10s",
            root_cause_hypothesis="Payment gateway network partition",
            confidence=0.9,
        ),
    )
    get_investigation_repository().save(inv)

    # 4. Remediation & Review
    rem = RemediationProposal(
        remediation_id="rem-f1",
        incident_id="inc-full",
        investigation_id="inv-f1",
        status=RemediationStatus.APPROVED,
        summary="Add payment circuit breaker",
        target_files=["checkout/gateway.py"],
        target_symbols=["process_payment"],
        proposed_changes=[],
        rationale="Prevents thread starvation",
        risks=[],
        validation_steps=[],
        evidence_references=[],
        confidence=0.85,
        created_at=t1,
        updated_at=t1,
    )
    get_remediation_repository().save(rem)

    rev = RemediationReview(
        review_id="rev-f1",
        incident_id="inc-full",
        remediation_id="rem-f1",
        investigation_id="inv-f1",
        decision=ReviewDecision.APPROVED,
        reviewer="sre-lead",
        comment="LGTM circuit breaker verified",
        created_at=t1,
    )
    get_review_repository().save(rev)

    # 5. Safe Action
    action = SafeAction(
        action_id="act-f1",
        project_id="proj-alpha",
        incident_id="inc-full",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        parameters={},
        fingerprint="fp1",
        requested_by_claim="alice",
        risk_level=RiskLevel.LOW,
        policy_status=PolicyStatus.ALLOWED,
        policy_denial_reason=None,
        approval_status=ApprovalStatus.APPROVED,
        execution_status=ExecutionStatus.SUCCEEDED,
        created_at=t1,
        updated_at=t2,
        approved_by_claim="bob",
        approved_at=t1,
        approved_fingerprint="fp1",
        executed_at=t1,
        completed_at=t2,
        execution_result={"status": "ok"},
    )
    get_action_store().create_action(action, [
        ActionAuditRecord(
            audit_id="aud-p1",
            action_id="act-f1",
            event_type="PROPOSED",
            actor_claim="alice",
            previous_state={},
            new_state={},
            message="Proposed connector test",
            created_at=t1,
        ),
        ActionAuditRecord(
            audit_id="aud-a1",
            action_id="act-f1",
            event_type="APPROVED",
            actor_claim="bob",
            previous_state={},
            new_state={},
            message="Approved connector test",
            created_at=t1,
        ),
        ActionAuditRecord(
            audit_id="aud-c1",
            action_id="act-f1",
            event_type="EXECUTION_COMPLETED",
            actor_claim="bob",
            previous_state={},
            new_state={},
            message="Connector test successful",
            created_at=t2,
        ),
    ])

    report_svc = get_report_service()
    report = report_svc.generate_report("inc-full", project_id="proj-alpha")

    assert report.incident.duration_seconds == (t2 - t0).total_seconds()
    assert report.detection_and_evidence.total_evidence_count == 1
    assert report.investigation.root_cause_hypothesis == "Payment gateway network partition"
    assert report.remediation.summary == "Add payment circuit breaker"
    assert len(report.human_decisions) >= 2  # remediation review + action approval
    assert len(report.safe_actions) == 1
    assert report.safe_actions[0].action_type == ActionType.TEST_CONNECTOR


def test_report_project_isolation_enforcement():
    """Verify cross-project report request raises ProjectIsolationError."""
    now = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)
    inc = Incident(
        id="inc-proj-test",
        title="Project Test Inc",
        summary="Summary",
        severity=Severity.LOW,
        status=IncidentStatus.OPEN,
        service="svc",
        environment="test",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )
    get_incident_repository().create(inc)

    report_svc = get_report_service()

    with pytest.raises(ProjectIsolationError):
        report_svc.generate_report("inc-proj-test", project_id="proj-bravo")
