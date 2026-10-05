"""Service aggregating canonical incident artifacts into an on-demand report read model."""

from datetime import datetime, timezone
import logging
from typing import List, Optional

from app.actions.store import SqliteActionStore
from app.agents.repository import InvestigationRepository
from app.incidents.models import Incident, IncidentStatus
from app.incidents.service import IncidentNotFoundError, IncidentService
from app.memory.models import HistoricalSearchQuery
from app.memory.service import IncidentMemoryService
from app.notifications.store import SqliteNotificationStore
from app.remediation.branch_repository import RemediationBranchRepository
from app.remediation.repository import RemediationRepository
from app.remediation.review_repository import RemediationReviewRepository
from app.reports.schemas import (
    DetectionAndEvidenceSection,
    EvidenceSummaryItem,
    HumanDecisionItem,
    IncidentOverviewSection,
    IncidentReportResponse,
    InvestigationSection,
    NotificationReportItem,
    ProposedChangeSummary,
    RemediationSection,
    SafeActionReportItem,
    SimilarIncidentReportItem,
    TimelineEventSchema,
)
from app.reports.timeline import ReportTimelineBuilder
from app.telemetry.repository import EvidenceRepository

logger = logging.getLogger("sentinelops.reports.service")


class ProjectIsolationError(Exception):
    """Raised when an incident is accessed outside its authorized project boundary."""

    def __init__(self, incident_id: str, project_id: str) -> None:
        super().__init__(f"Incident '{incident_id}' does not belong to project '{project_id}'.")
        self.incident_id = incident_id
        self.project_id = project_id


class ReportService:
    """Orchestrates on-demand materialization of factual incident reports."""

    def __init__(
        self,
        incident_service: IncidentService,
        evidence_repository: EvidenceRepository,
        investigation_repository: InvestigationRepository,
        remediation_repository: RemediationRepository,
        review_repository: RemediationReviewRepository,
        branch_repository: RemediationBranchRepository,
        action_store: SqliteActionStore,
        notification_store: SqliteNotificationStore,
        memory_service: IncidentMemoryService,
    ) -> None:
        self._incident_service = incident_service
        self._evidence_repo = evidence_repository
        self._investigation_repo = investigation_repository
        self._remediation_repo = remediation_repository
        self._review_repo = review_repository
        self._branch_repo = branch_repository
        self._action_store = action_store
        self._notification_store = notification_store
        self._memory_service = memory_service

    def generate_report(self, incident_id: str, project_id: str) -> IncidentReportResponse:
        """Assembles a complete, factual, project-isolated report for an incident on demand."""
        # 1. Fetch and validate Incident and Project Boundary
        incident = self._incident_service.get_incident(incident_id)
        if incident.project_id != project_id:
            logger.warning(
                "Access denied: Incident %s belongs to project '%s', query specified '%s'",
                incident_id,
                incident.project_id,
                project_id,
            )
            raise ProjectIsolationError(incident_id, project_id)

        now = datetime.now(timezone.utc)

        # Calculate duration if terminal status
        duration_seconds: Optional[float] = None
        if incident.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
            duration_seconds = max(0.0, (incident.updated_at - incident.created_at).total_seconds())

        overview = IncidentOverviewSection(
            incident_id=incident.id,
            project_id=incident.project_id,
            title=incident.title,
            summary=incident.summary,
            severity=incident.severity,
            status=incident.status,
            service=incident.service,
            environment=incident.environment,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
            duration_seconds=duration_seconds,
        )

        # 2. Evidence
        ev_items = self._evidence_repo.list_for_incident(incident.id)
        first_ev = ev_items[0].timestamp if ev_items else None
        last_ev = ev_items[-1].timestamp if ev_items else None
        summary_ev = [
            EvidenceSummaryItem(
                id=e.id,
                type=e.type.value if hasattr(e.type, "value") else str(e.type),
                source=e.source,
                timestamp=e.timestamp,
                level=e.level,
                event=e.event,
                message=e.message,
                endpoint=e.endpoint,
                exception_type=e.exception_type,
                request_id=e.request_id,
            )
            for e in ev_items
        ]
        detection_evidence = DetectionAndEvidenceSection(
            total_evidence_count=len(ev_items),
            first_evidence_at=first_ev,
            last_evidence_at=last_ev,
            items=summary_ev,
        )

        # 3. Investigation
        investigation_domain = self._investigation_repo.get_by_incident_id(incident.id)
        investigation_section: Optional[InvestigationSection] = None
        if investigation_domain:
            rca = investigation_domain.rca
            val = investigation_domain.validation
            ca = investigation_domain.code_analysis
            investigation_section = InvestigationSection(
                investigation_id=investigation_domain.investigation_id,
                status=investigation_domain.status.value if hasattr(investigation_domain.status, "value") else str(investigation_domain.status),
                created_at=investigation_domain.created_at,
                completed_at=investigation_domain.completed_at,
                failure_location=rca.failure_location if rca else None,
                triggering_condition=rca.triggering_condition if rca else None,
                root_cause_hypothesis=rca.root_cause_hypothesis if rca else None,
                summary=rca.summary if rca else None,
                confidence=rca.confidence if rca else None,
                uncertainties=rca.uncertainties if rca else [],
                is_valid=val.valid if val else None,
                validation_issues=val.issues if val else [],
                relevant_files=ca.relevant_files if ca else [],
                relevant_symbols=ca.relevant_symbols if ca else [],
            )

        # 4. Remediation & Branch
        remediation_domain = self._remediation_repo.get_by_incident_id(incident.id)
        branch_domain = self._branch_repo.get_by_incident_id(incident.id)
        remediation_section: Optional[RemediationSection] = None
        if remediation_domain:
            remediation_section = RemediationSection(
                remediation_id=remediation_domain.remediation_id,
                status=remediation_domain.status.value if hasattr(remediation_domain.status, "value") else str(remediation_domain.status),
                summary=remediation_domain.summary,
                rationale=remediation_domain.rationale,
                risks=remediation_domain.risks,
                validation_steps=remediation_domain.validation_steps,
                confidence=remediation_domain.confidence,
                proposed_changes=[
                    ProposedChangeSummary(
                        file_path=c.file_path,
                        change_type=c.change_type.value if hasattr(c.change_type, "value") else str(c.change_type),
                        description=c.description,
                        reason=c.reason,
                        symbol=c.symbol,
                    )
                    for c in remediation_domain.proposed_changes
                ],
                branch_name=branch_domain.branch_name if branch_domain else None,
                base_commit=branch_domain.base_commit if branch_domain else None,
            )

        # 5. Human Decisions (Reviews + Safe Action Approval / Rejection)
        human_decisions: List[HumanDecisionItem] = []
        reviews = self._review_repo.list_for_incident(incident.id)
        for r in reviews:
            human_decisions.append(
                HumanDecisionItem(
                    decision_type="remediation_review",
                    decision=r.decision.value if hasattr(r.decision, "value") else str(r.decision),
                    actor=r.reviewer,
                    comment_or_reason=r.comment,
                    timestamp=r.created_at,
                    target_id=r.remediation_id,
                )
            )

        # 6. Safe Actions & Audits
        actions = self._action_store.list_actions(project_id=incident.project_id, incident_id=incident.id)
        safe_action_items: List[SafeActionReportItem] = []
        all_action_audits = []

        for a in actions:
            safe_action_items.append(
                SafeActionReportItem(
                    action_id=a.action_id,
                    action_type=a.action_type,
                    target_type=a.target_type,
                    target_id=a.target_id,
                    risk_level=a.risk_level,
                    policy_status=a.policy_status,
                    policy_denial_reason=a.policy_denial_reason,
                    approval_status=a.approval_status,
                    approved_by=a.approved_by_claim,
                    approved_at=a.approved_at,
                    rejection_reason=a.rejection_reason,
                    execution_status=a.execution_status,
                    executed_at=a.executed_at,
                    completed_at=a.completed_at,
                    execution_result=a.execution_result,
                    failure_reason=a.failure_reason,
                    created_at=a.created_at,
                )
            )
            audits = self._action_store.list_audit_records(a.action_id)
            all_action_audits.extend(audits)

            for aud in audits:
                if aud.event_type == "APPROVED":
                    human_decisions.append(
                        HumanDecisionItem(
                            decision_type="safe_action_approval",
                            decision="approved",
                            actor=aud.actor_claim,
                            comment_or_reason=aud.message,
                            timestamp=aud.created_at,
                            target_id=a.action_id,
                        )
                    )
                elif aud.event_type == "REJECTED":
                    human_decisions.append(
                        HumanDecisionItem(
                            decision_type="safe_action_rejection",
                            decision="rejected",
                            actor=aud.actor_claim,
                            comment_or_reason=a.rejection_reason or aud.message,
                            timestamp=aud.created_at,
                            target_id=a.action_id,
                        )
                    )

        # Sort decisions chronologically
        human_decisions.sort(key=lambda d: d.timestamp)

        # 7. Notifications
        notifications = self._notification_store.list_notifications(
            project_id=incident.project_id, incident_id=incident.id
        )
        notification_items = [
            NotificationReportItem(
                notification_id=n.notification_id,
                channel=n.channel,
                recipient=n.recipient,
                title=n.title,
                notification_type=n.notification_type,
                delivery_status=n.delivery_status,
                attempt_count=n.attempt_count,
                last_attempt_at=n.last_attempt_at,
                delivered_at=n.delivered_at,
                failure_reason=n.failure_reason,
                created_at=n.created_at,
            )
            for n in notifications
        ]

        # 8. Operational Memory / Similar Historical Incidents
        similar_items: List[SimilarIncidentReportItem] = []
        ra = investigation_domain.runtime_analysis if investigation_domain else None
        ca = investigation_domain.code_analysis if investigation_domain else None
        rca = investigation_domain.rca if investigation_domain else None

        query = HistoricalSearchQuery(
            current_incident_id=incident.id,
            service=incident.service,
            environment=incident.environment,
            exception_type=ra.exception_type if ra else None,
            endpoint=ra.endpoint if ra else None,
            query_text=rca.summary if rca else incident.summary,
            relevant_symbols=list(ca.relevant_symbols) if ca else [],
            relevant_files=list(ca.relevant_files) if ca else [],
            limit=5,
        )
        matched_contexts = self._memory_service.search_history(query)
        for mc in matched_contexts:
            # Enforce project isolation on candidate
            cand_mem = self._memory_service.get_memory(mc.incident_id)
            if not cand_mem:
                continue
            # Look up incident in incident_service to verify project boundary
            try:
                cand_inc = self._incident_service.get_incident(mc.incident_id)
                if cand_inc.project_id != incident.project_id:
                    continue  # Cross-project candidate dropped
                cand_sev = cand_inc.severity.value if hasattr(cand_inc.severity, "value") else str(cand_inc.severity)
                cand_stat = cand_inc.status.value if hasattr(cand_inc.status, "value") else str(cand_inc.status)
                cand_created = cand_inc.created_at
            except IncidentNotFoundError:
                cand_sev = None
                cand_stat = None
                cand_created = cand_mem.created_at

            similar_items.append(
                SimilarIncidentReportItem(
                    incident_id=mc.incident_id,
                    project_id=incident.project_id,
                    title=mc.title,
                    service=mc.service,
                    severity=cand_sev,
                    status=cand_stat,
                    created_at=cand_created,
                    similarity_score=mc.similarity_score,
                    matched_signals=mc.matched_signals,
                    failure_location=mc.failure_location,
                    triggering_condition=mc.triggering_condition,
                    root_cause_hypothesis=mc.root_cause_hypothesis,
                    resolution_notes=mc.resolution_notes,
                )
            )

        # 9. Build Deterministic Timeline
        timeline_events = ReportTimelineBuilder.build_timeline(
            incident=incident,
            evidence_items=ev_items,
            investigation=investigation_domain,
            remediation=remediation_domain,
            reviews=reviews,
            actions=actions,
            action_audits=all_action_audits,
            notifications=notifications,
        )
        timeline_schemas = [
            TimelineEventSchema(
                timestamp=e.timestamp,
                event_type=e.event_type,
                title=e.title,
                description=e.description,
                source=e.source,
                actor=e.actor,
                metadata=e.metadata,
            )
            for e in timeline_events
        ]

        return IncidentReportResponse(
            incident=overview,
            detection_and_evidence=detection_evidence,
            investigation=investigation_section,
            remediation=remediation_section,
            human_decisions=human_decisions,
            safe_actions=safe_action_items,
            notifications=notification_items,
            similar_incidents=similar_items,
            timeline=timeline_schemas,
            generated_at=now,
        )
