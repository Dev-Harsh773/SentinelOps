"""Tests for Stage 19 timeline synthesizer and deterministic ordering."""

from datetime import datetime, timezone
import pytest

from app.actions.models import ActionAuditRecord, ActionType, ApprovalStatus, ExecutionStatus, PolicyStatus, RiskLevel, SafeAction, TargetType
from app.agents.models import EvidenceReference, Investigation, InvestigationStatus, RootCauseAnalysis
from app.incidents.models import Incident, IncidentStatus, Severity
from app.notifications.models import DeliveryStatus, Notification, NotificationChannel, NotificationType
from app.remediation.models import ChangeType, ProposedChange, RemediationProposal, RemediationReview, RemediationStatus, ReviewDecision
from app.reports.models import TimelineEventType
from app.reports.timeline import ReportTimelineBuilder
from app.telemetry.models import Evidence, EvidenceType


def test_timeline_ordering_chronological():
    """Verify events are strictly sorted by UTC timestamp ascending."""
    t1 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc)
    t3 = datetime(2026, 10, 1, 10, 10, tzinfo=timezone.utc)

    incident = Incident(
        id="inc-t1",
        title="Test Incident",
        summary="Summary",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="order-svc",
        environment="prod",
        created_at=t1,
        updated_at=t1,
        project_id="test-proj",
    )
    ev = Evidence(
        id="ev-1",
        incident_id="inc-t1",
        type=EvidenceType.RUNTIME_LOG,
        source="log",
        timestamp=t2,
        service="order-svc",
        level="ERROR",
        event="timeout",
        message="Order timed out",
        endpoint="/orders",
        exception_type="TimeoutError",
        created_at=t2,
    )
    inv = Investigation(
        investigation_id="inv-1",
        incident_id="inc-t1",
        status=InvestigationStatus.COMPLETED,
        created_at=t2,
        completed_at=t3,
        rca=RootCauseAnalysis(
            failure_location="order.py",
            triggering_condition="timeout > 5s",
            root_cause_hypothesis="DB connection slow",
        ),
    )

    events = ReportTimelineBuilder.build_timeline(
        incident=incident,
        evidence_items=[ev],
        investigation=inv,
    )

    assert len(events) == 4
    assert events[0].event_type == TimelineEventType.INCIDENT_CREATED
    assert events[0].timestamp == t1
    assert events[1].event_type == TimelineEventType.EVIDENCE_INGESTED
    assert events[1].timestamp == t2
    assert events[2].event_type == TimelineEventType.INVESTIGATION_STARTED
    assert events[2].timestamp == t2
    assert events[3].event_type == TimelineEventType.INVESTIGATION_COMPLETED
    assert events[3].timestamp == t3


def test_timeline_tie_breaking_priority():
    """Verify identical timestamps sort deterministically by defined event priority."""
    t = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    incident = Incident(
        id="inc-tie",
        title="Tie Incident",
        summary="Summary",
        severity=Severity.MEDIUM,
        status=IncidentStatus.OPEN,
        service="auth",
        environment="prod",
        created_at=t,
        updated_at=t,
        project_id="test-proj",
    )
    ev = Evidence(
        id="ev-tie",
        incident_id="inc-tie",
        type=EvidenceType.RUNTIME_LOG,
        source="log",
        timestamp=t,
        service="auth",
        level="ERROR",
        event="auth_fail",
        message="Auth failure",
        endpoint="/login",
        exception_type="AuthError",
        created_at=t,
    )

    events = ReportTimelineBuilder.build_timeline(
        incident=incident,
        evidence_items=[ev],
    )

    assert len(events) == 2
    # Incident Created (priority 10) must precede Evidence Ingested (priority 20)
    assert events[0].event_type == TimelineEventType.INCIDENT_CREATED
    assert events[1].event_type == TimelineEventType.EVIDENCE_INGESTED


def test_timeline_exact_stage18_audit_events():
    """Verify exact Stage 18 audit events map to timeline without synthetic names."""
    t = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    incident = Incident(
        id="inc-a",
        title="Action Inc",
        summary="Summary",
        severity=Severity.LOW,
        status=IncidentStatus.OPEN,
        service="svc",
        environment="prod",
        created_at=t,
        updated_at=t,
        project_id="proj-a",
    )

    audits = [
        ActionAuditRecord(
            audit_id="aud-1",
            action_id="act-1",
            event_type="PROPOSED",
            actor_claim="operator",
            previous_state={},
            new_state={},
            message="Action proposed",
            created_at=datetime(2026, 10, 1, 12, 1, tzinfo=timezone.utc),
        ),
        ActionAuditRecord(
            audit_id="aud-2",
            action_id="act-1",
            event_type="APPROVED",
            actor_claim="alice",
            previous_state={},
            new_state={},
            message="Action approved",
            created_at=datetime(2026, 10, 1, 12, 2, tzinfo=timezone.utc),
        ),
        ActionAuditRecord(
            audit_id="aud-3",
            action_id="act-1",
            event_type="EXECUTION_STARTED",
            actor_claim="alice",
            previous_state={},
            new_state={},
            message="Execution started",
            created_at=datetime(2026, 10, 1, 12, 3, tzinfo=timezone.utc),
        ),
        ActionAuditRecord(
            audit_id="aud-4",
            action_id="act-1",
            event_type="EXECUTION_COMPLETED",
            actor_claim="alice",
            previous_state={},
            new_state={},
            message="Execution succeeded",
            created_at=datetime(2026, 10, 1, 12, 4, tzinfo=timezone.utc),
        ),
        ActionAuditRecord(
            audit_id="aud-5",
            action_id="act-2",
            event_type="PREREQUISITE_CONFLICT_ABORTED",
            actor_claim="bob",
            previous_state={},
            new_state={},
            message="Prerequisite conflict",
            created_at=datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc),
        ),
        ActionAuditRecord(
            audit_id="aud-6",
            action_id="act-3",
            event_type="EXECUTION_ABORTED_ON_RESTART",
            actor_claim="system",
            previous_state={},
            new_state={},
            message="Aborted on restart",
            created_at=datetime(2026, 10, 1, 12, 6, tzinfo=timezone.utc),
        ),
    ]

    events = ReportTimelineBuilder.build_timeline(
        incident=incident,
        evidence_items=[],
        action_audits=audits,
    )

    types = [e.event_type for e in events]
    assert TimelineEventType.SAFE_ACTION_PROPOSED in types
    assert TimelineEventType.SAFE_ACTION_APPROVED in types
    assert TimelineEventType.SAFE_ACTION_EXECUTION_STARTED in types
    assert TimelineEventType.SAFE_ACTION_EXECUTION_COMPLETED in types
    assert TimelineEventType.SAFE_ACTION_ABORTED in types


def test_timeline_notification_timing_accuracy():
    """Verify notification events use delivered_at / last_attempt_at and omit if None."""
    t = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    t_del = datetime(2026, 10, 1, 12, 10, tzinfo=timezone.utc)
    t_fail = datetime(2026, 10, 1, 12, 15, tzinfo=timezone.utc)

    incident = Incident(
        id="inc-n",
        title="Notif Inc",
        summary="Summary",
        severity=Severity.LOW,
        status=IncidentStatus.OPEN,
        service="svc",
        environment="prod",
        created_at=t,
        updated_at=t,
        project_id="proj-n",
    )

    notif_delivered = Notification(
        notification_id="n-1",
        project_id="proj-n",
        incident_id="inc-n",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.LOW,
        title="Delivered Alert",
        message="Msg",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="https://webhook.example.com",
        delivery_status=DeliveryStatus.DELIVERED,
        delivered_at=t_del,
        created_at=t,
        updated_at=t_del,
    )

    notif_failed = Notification(
        notification_id="n-2",
        project_id="proj-n",
        incident_id="inc-n",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.LOW,
        title="Failed Alert",
        message="Msg",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="https://fail.example.com",
        delivery_status=DeliveryStatus.FAILED,
        last_attempt_at=t_fail,
        created_at=t,
        updated_at=t_fail,
    )

    notif_unattempted_fail = Notification(
        notification_id="n-3",
        project_id="proj-n",
        incident_id="inc-n",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.LOW,
        title="No Attempt Alert",
        message="Msg",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="https://fail.example.com",
        delivery_status=DeliveryStatus.FAILED,
        last_attempt_at=None,
        created_at=t,
        updated_at=t,
    )

    events = ReportTimelineBuilder.build_timeline(
        incident=incident,
        evidence_items=[],
        notifications=[notif_delivered, notif_failed, notif_unattempted_fail],
    )

    notif_events = [e for e in events if "notification" in e.source]
    assert len(notif_events) == 2
    assert notif_events[0].event_type == TimelineEventType.NOTIFICATION_DELIVERED
    assert notif_events[0].timestamp == t_del
    assert notif_events[1].event_type == TimelineEventType.NOTIFICATION_FAILED
    assert notif_events[1].timestamp == t_fail


def test_timeline_no_fabricated_status_transitions():
    """Verify updating updated_at does not fabricate an unverified STATUS_TRANSITION event."""
    t_create = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    t_update = datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc)

    incident = Incident(
        id="inc-mod",
        title="Mod Inc",
        summary="Summary",
        severity=Severity.HIGH,
        status=IncidentStatus.RESOLVED,
        service="svc",
        environment="prod",
        created_at=t_create,
        updated_at=t_update,
        project_id="proj-mod",
    )

    events = ReportTimelineBuilder.build_timeline(
        incident=incident,
        evidence_items=[],
    )

    # Should only contain INCIDENT_CREATED, zero synthetic transitions
    assert len(events) == 1
    assert events[0].event_type == TimelineEventType.INCIDENT_CREATED
