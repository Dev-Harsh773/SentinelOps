"""FastAPI dependency injection providers for Incident Report generation."""

from fastapi import Depends

from app.actions.dependencies import get_action_store
from app.actions.store import SqliteActionStore
from app.agents.dependencies import get_investigation_repository
from app.agents.repository import InvestigationRepository
from app.incidents.dependencies import get_incident_service
from app.incidents.service import IncidentService
from app.memory.dependencies import get_memory_service
from app.memory.service import IncidentMemoryService
from app.notifications.dependencies import get_notification_store
from app.notifications.store import SqliteNotificationStore
from app.remediation.branch_repository import RemediationBranchRepository
from app.remediation.dependencies import (
    get_branch_repository,
    get_remediation_repository,
    get_review_repository,
)
from app.remediation.repository import RemediationRepository
from app.remediation.review_repository import RemediationReviewRepository
from app.reports.service import ReportService
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.repository import EvidenceRepository


from fastapi import Depends
from fastapi.params import Depends as DependsClass
from typing import Any, Optional


def get_report_service(
    incident_service: Any = Depends(get_incident_service),
    evidence_repository: Any = Depends(get_evidence_repository),
    investigation_repository: Any = Depends(get_investigation_repository),
    remediation_repository: Any = Depends(get_remediation_repository),
    review_repository: Any = Depends(get_review_repository),
    branch_repository: Any = Depends(get_branch_repository),
    action_store: Any = Depends(get_action_store),
    notification_store: Any = Depends(get_notification_store),
    memory_service: Any = Depends(get_memory_service),
) -> ReportService:
    """Provides dynamic, request-scoped ReportService wired with fresh open stores."""
    if isinstance(incident_service, DependsClass) or incident_service is None:
        incident_service = get_incident_service()
    if isinstance(evidence_repository, DependsClass) or evidence_repository is None:
        evidence_repository = get_evidence_repository()
    if isinstance(investigation_repository, DependsClass) or investigation_repository is None:
        investigation_repository = get_investigation_repository()
    if isinstance(remediation_repository, DependsClass) or remediation_repository is None:
        remediation_repository = get_remediation_repository()
    if isinstance(review_repository, DependsClass) or review_repository is None:
        review_repository = get_review_repository()
    if isinstance(branch_repository, DependsClass) or branch_repository is None:
        branch_repository = get_branch_repository()
    if isinstance(action_store, DependsClass) or action_store is None:
        action_store = get_action_store()
    if isinstance(notification_store, DependsClass) or notification_store is None:
        notification_store = get_notification_store()
    if isinstance(memory_service, DependsClass) or memory_service is None:
        memory_service = get_memory_service()

    return ReportService(
        incident_service=incident_service,
        evidence_repository=evidence_repository,
        investigation_repository=investigation_repository,
        remediation_repository=remediation_repository,
        review_repository=review_repository,
        branch_repository=branch_repository,
        action_store=action_store,
        notification_store=notification_store,
        memory_service=memory_service,
    )
