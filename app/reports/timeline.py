"""Deterministic timeline synthesizer normalizing facts from canonical incident sources."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.actions.models import ActionAuditRecord, SafeAction
from app.agents.models import Investigation, InvestigationStatus
from app.incidents.models import Incident
from app.notifications.models import DeliveryStatus, Notification
from app.remediation.models import RemediationProposal, RemediationReview
from app.reports.models import TimelineEvent, TimelineEventType
from app.telemetry.models import Evidence

# Deterministic tie-breaking priority when timestamps are identical
_EVENT_PRIORITY = {
    TimelineEventType.INCIDENT_CREATED: 10,
    TimelineEventType.EVIDENCE_INGESTED: 20,
    TimelineEventType.INVESTIGATION_STARTED: 30,
    TimelineEventType.INVESTIGATION_COMPLETED: 40,
    TimelineEventType.INVESTIGATION_FAILED: 45,
    TimelineEventType.REMEDIATION_PROPOSED: 50,
    TimelineEventType.REMEDIATION_REVIEWED: 60,
    TimelineEventType.SAFE_ACTION_PROPOSED: 70,
    TimelineEventType.SAFE_ACTION_POLICY_DENIED: 75,
    TimelineEventType.SAFE_ACTION_APPROVED: 80,
    TimelineEventType.SAFE_ACTION_REJECTED: 85,
    TimelineEventType.SAFE_ACTION_EXECUTION_STARTED: 90,
    TimelineEventType.SAFE_ACTION_EXECUTION_COMPLETED: 95,
    TimelineEventType.SAFE_ACTION_EXECUTION_FAILED: 96,
    TimelineEventType.SAFE_ACTION_ABORTED: 97,
    TimelineEventType.NOTIFICATION_DELIVERED: 100,
    TimelineEventType.NOTIFICATION_FAILED: 105,
}

# Accurate Stage 18 audit event types mapping
_SAFE_ACTION_AUDIT_MAP = {
    "PROPOSED": TimelineEventType.SAFE_ACTION_PROPOSED,
    "POLICY_DENIED": TimelineEventType.SAFE_ACTION_POLICY_DENIED,
    "APPROVED": TimelineEventType.SAFE_ACTION_APPROVED,
    "REJECTED": TimelineEventType.SAFE_ACTION_REJECTED,
    "EXECUTION_STARTED": TimelineEventType.SAFE_ACTION_EXECUTION_STARTED,
    "POLICY_REVALIDATION_FAILED": TimelineEventType.SAFE_ACTION_ABORTED,
    "EXECUTION_COMPLETED": TimelineEventType.SAFE_ACTION_EXECUTION_COMPLETED,
    "EXECUTION_FAILED": TimelineEventType.SAFE_ACTION_EXECUTION_FAILED,
    "PREREQUISITE_CONFLICT_ABORTED": TimelineEventType.SAFE_ACTION_ABORTED,
    "EXECUTION_ABORTED_ON_RESTART": TimelineEventType.SAFE_ACTION_ABORTED,
}


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime has timezone set to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ReportTimelineBuilder:
    """Extracts, normalizes, and sorts canonical events into a deterministic chronological timeline."""

    @classmethod
    def build_timeline(
        cls,
        incident: Incident,
        evidence_items: List[Evidence],
        investigation: Optional[Investigation] = None,
        remediation: Optional[RemediationProposal] = None,
        reviews: Optional[List[RemediationReview]] = None,
        actions: Optional[List[SafeAction]] = None,
        action_audits: Optional[List[ActionAuditRecord]] = None,
        notifications: Optional[List[Notification]] = None,
    ) -> List[TimelineEvent]:
        raw_events: List[TimelineEvent] = []

        # 1. Incident Creation
        raw_events.append(
            TimelineEvent(
                timestamp=_ensure_utc(incident.created_at),
                event_type=TimelineEventType.INCIDENT_CREATED,
                title="Incident Created",
                description=f"Incident '{incident.title}' was detected/opened with severity {incident.severity.value}.",
                source="incident",
                actor="system",
                metadata={"incident_id": incident.id, "severity": incident.severity.value},
            )
        )

        # 2. Evidence Ingestion
        for ev in evidence_items:
            raw_events.append(
                TimelineEvent(
                    timestamp=_ensure_utc(ev.timestamp),
                    event_type=TimelineEventType.EVIDENCE_INGESTED,
                    title=f"Evidence Ingested: {ev.event}",
                    description=ev.message,
                    source="telemetry",
                    actor="collector",
                    metadata={"evidence_id": ev.id, "level": ev.level, "source": ev.source},
                )
            )

        # 3. Investigation Lifecycle
        if investigation:
            raw_events.append(
                TimelineEvent(
                    timestamp=_ensure_utc(investigation.created_at),
                    event_type=TimelineEventType.INVESTIGATION_STARTED,
                    title="Investigation Started",
                    description="AI Investigation workflow initiated.",
                    source="investigation",
                    actor="ai_agent",
                    metadata={"investigation_id": investigation.investigation_id},
                )
            )
            if investigation.completed_at and investigation.status == InvestigationStatus.COMPLETED:
                rca_hyp = investigation.rca.root_cause_hypothesis if investigation.rca else "Root cause analysis completed."
                raw_events.append(
                    TimelineEvent(
                        timestamp=_ensure_utc(investigation.completed_at),
                        event_type=TimelineEventType.INVESTIGATION_COMPLETED,
                        title="Investigation Completed",
                        description=rca_hyp,
                        source="investigation",
                        actor="ai_agent",
                        metadata={"investigation_id": investigation.investigation_id},
                    )
                )
            elif investigation.completed_at and investigation.status == InvestigationStatus.FAILED:
                raw_events.append(
                    TimelineEvent(
                        timestamp=_ensure_utc(investigation.completed_at),
                        event_type=TimelineEventType.INVESTIGATION_FAILED,
                        title="Investigation Failed",
                        description="Investigation failed: " + ("; ".join(investigation.errors) if investigation.errors else "Unknown failure"),
                        source="investigation",
                        actor="ai_agent",
                        metadata={"investigation_id": investigation.investigation_id},
                    )
                )

        # 4. Remediation Proposal Lifecycle
        if remediation:
            raw_events.append(
                TimelineEvent(
                    timestamp=_ensure_utc(remediation.created_at),
                    event_type=TimelineEventType.REMEDIATION_PROPOSED,
                    title="Remediation Proposed",
                    description=remediation.summary,
                    source="remediation",
                    actor="ai_agent",
                    metadata={"remediation_id": remediation.remediation_id},
                )
            )

        # 5. Remediation Reviews
        if reviews:
            for rev in reviews:
                raw_events.append(
                    TimelineEvent(
                        timestamp=_ensure_utc(rev.created_at),
                        event_type=TimelineEventType.REMEDIATION_REVIEWED,
                        title=f"Remediation Review: {rev.decision.value.capitalize()}",
                        description=rev.comment or f"Remediation {rev.decision.value} by {rev.reviewer}",
                        source="remediation_review",
                        actor=rev.reviewer,
                        metadata={"review_id": rev.review_id, "decision": rev.decision.value},
                    )
                )

        # 6. Safe Actions Lifecycle (from exact ActionAuditRecord events)
        if action_audits:
            for audit in action_audits:
                mapped_type = _SAFE_ACTION_AUDIT_MAP.get(audit.event_type)
                if not mapped_type:
                    continue  # E.g. POLICY_EVALUATED omitted to avoid cluttering high-level timeline

                title = f"Safe Action: {audit.event_type.replace('_', ' ').title()}"
                desc = audit.message or f"Action {audit.action_id} reached state {audit.event_type}"
                raw_events.append(
                    TimelineEvent(
                        timestamp=_ensure_utc(audit.created_at),
                        event_type=mapped_type,
                        title=title,
                        description=desc,
                        source="safe_action",
                        actor=audit.actor_claim,
                        metadata={
                            "action_id": audit.action_id,
                            "audit_id": audit.audit_id,
                            "event_type": audit.event_type,
                        },
                    )
                )

        # 7. Notifications Lifecycle (delivered_at and last_attempt_at only)
        if notifications:
            for n in notifications:
                if n.delivery_status == DeliveryStatus.DELIVERED and n.delivered_at is not None:
                    raw_events.append(
                        TimelineEvent(
                            timestamp=_ensure_utc(n.delivered_at),
                            event_type=TimelineEventType.NOTIFICATION_DELIVERED,
                            title=f"Notification Delivered ({n.channel.value})",
                            description=f"Delivered to {n.recipient}: {n.title}",
                            source="notification",
                            actor="system",
                            metadata={"notification_id": n.notification_id, "channel": n.channel.value},
                        )
                    )
                elif n.delivery_status == DeliveryStatus.FAILED and n.last_attempt_at is not None:
                    raw_events.append(
                        TimelineEvent(
                            timestamp=_ensure_utc(n.last_attempt_at),
                            event_type=TimelineEventType.NOTIFICATION_FAILED,
                            title=f"Notification Failed ({n.channel.value})",
                            description=f"Delivery to {n.recipient} failed: {n.failure_reason or 'Delivery error'}",
                            source="notification",
                            actor="system",
                            metadata={"notification_id": n.notification_id, "channel": n.channel.value},
                        )
                    )
                # If last_attempt_at is None, we omit the failure timeline event to preserve truthful timing.

        # Sort strictly ascending by timestamp, then by deterministic event priority, then by title
        raw_events.sort(key=lambda e: (e.timestamp, _EVENT_PRIORITY.get(e.event_type, 999), e.title))
        return raw_events
