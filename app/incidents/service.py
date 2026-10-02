"""Incident business logic service and lifecycle validation rules."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import logging
from typing import List, Optional, Set, Tuple
import uuid

from app.incidents.models import Incident, IncidentStatus
from app.incidents.repository import IncidentRepository
from app.incidents.schemas import IncidentCreateRequest

logger = logging.getLogger("sentinelops.incidents.service")


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


class IncidentLifecycleListener(ABC):
    """Observer contract for incident lifecycle events."""

    @abstractmethod
    def on_incident_created(self, incident: Incident) -> None:
        """Invoked synchronously after an incident is durably created."""
        pass

    @abstractmethod
    def on_incident_status_changed(
        self, incident: Incident, old_status: IncidentStatus, new_status: IncidentStatus
    ) -> None:
        """Invoked synchronously after an incident status transition is durably persisted."""
        pass


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

    def __init__(
        self,
        repository: IncidentRepository,
        listeners: Optional[List[IncidentLifecycleListener]] = None,
    ) -> None:
        self._repository = repository
        self._listeners: List[IncidentLifecycleListener] = list(listeners) if listeners else []

    def add_listener(self, listener: IncidentLifecycleListener) -> None:
        """Register a lifecycle listener idempotently."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: IncidentLifecycleListener) -> None:
        """Remove a lifecycle listener."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def clear_listeners(self) -> None:
        """Clear all registered listeners. Reserved strictly for test isolation."""
        self._listeners.clear()

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
            project_id=request.project_id or "default",
        )
        created = self._repository.create(incident)
        for listener in self._listeners:
            try:
                listener.on_incident_created(created)
            except Exception as exc:
                logger.error("IncidentLifecycleListener error on creation: %s", exc, exc_info=True)
        return created

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

        old_status = incident.status
        incident.status = new_status
        incident.updated_at = datetime.now(timezone.utc)
        updated = self._repository.update(incident)
        for listener in self._listeners:
            try:
                listener.on_incident_status_changed(updated, old_status, new_status)
            except Exception as exc:
                logger.error("IncidentLifecycleListener error on status update: %s", exc, exc_info=True)
        return updated
