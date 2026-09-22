"""Incident business logic service and lifecycle validation rules."""

from datetime import datetime, timezone
from typing import List, Set, Tuple
import uuid

from app.incidents.models import Incident, IncidentStatus
from app.incidents.repository import IncidentRepository
from app.incidents.schemas import IncidentCreateRequest


class IncidentNotFoundError(Exception):
    """Raised when an incident identifier does not exist in storage."""

    def __init__(self, incident_id: str) -> None:
        super().__init__(f"Incident with ID '{incident_id}' not found.")
        self.incident_id = incident_id


class InvalidStatusTransitionError(Exception):
    """Raised when an illegal status transition is attempted."""

    def __init__(self, current_status: IncidentStatus, target_status: IncidentStatus) -> None:
        super().__init__(
            f"Cannot transition incident from {current_status.value.upper()} to {target_status.value.upper()}."
        )
        self.current_status = current_status
        self.target_status = target_status


# Strictly allowed transitions for Stage 1 incident lifecycle:
# OPEN -> INVESTIGATING
# OPEN -> RESOLVED
# INVESTIGATING -> RESOLVED
# RESOLVED -> CLOSED
ALLOWED_TRANSITIONS: Set[Tuple[IncidentStatus, IncidentStatus]] = {
    (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING),
    (IncidentStatus.OPEN, IncidentStatus.RESOLVED),
    (IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED),
    (IncidentStatus.RESOLVED, IncidentStatus.CLOSED),
}


class IncidentService:
    """Orchestrates incident domain operations, enforcing lifecycle and validation rules."""

    def __init__(self, repository: IncidentRepository) -> None:
        self._repository = repository

    def create_incident(self, request: IncidentCreateRequest) -> Incident:
        """Create and store a new incident with default OPEN status and UTC timestamps."""
        now = datetime.now(timezone.utc)
        incident = Incident(
            id=str(uuid.uuid4()),
            title=request.title,
            summary=request.summary,
            severity=request.severity,
            status=IncidentStatus.OPEN,
            service=request.service,
            environment=request.environment,
            created_at=now,
            updated_at=now,
        )
        return self._repository.create(incident)

    def get_incident(self, incident_id: str) -> Incident:
        """Retrieve an incident by ID or raise IncidentNotFoundError."""
        incident = self._repository.get_by_id(incident_id)
        if not incident:
            raise IncidentNotFoundError(incident_id)
        return incident

    def list_incidents(self) -> List[Incident]:
        """Return all active and historical incidents."""
        return self._repository.list_all()

    def update_status(self, incident_id: str, new_status: IncidentStatus) -> Incident:
        """Validate and apply a lifecycle status transition, advancing updated_at."""
        incident = self.get_incident(incident_id)

        # Enforce strict Stage 1 lifecycle transitions
        transition = (incident.status, new_status)
        if transition not in ALLOWED_TRANSITIONS:
            raise InvalidStatusTransitionError(incident.status, new_status)

        incident.status = new_status
        incident.updated_at = datetime.now(timezone.utc)
        return self._repository.update(incident)
