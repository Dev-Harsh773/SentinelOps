"""Centralized dependency injection providers for Incident components."""

from functools import lru_cache
from app.incidents.repository import IncidentRepository, InMemoryIncidentRepository
from app.incidents.service import IncidentService

# Single shared in-memory repository instance for the running application lifetime
_shared_repository = InMemoryIncidentRepository()


def get_incident_repository() -> IncidentRepository:
    """Provide the shared incident repository instance."""
    return _shared_repository


@lru_cache
def get_incident_service() -> IncidentService:
    """Provide the incident service configured with the shared repository."""
    return IncidentService(repository=get_incident_repository())
