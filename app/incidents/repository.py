"""Incident repository interface and in-memory implementation.

Abstracts storage operations behind an interface so Stage 1 can function
without a database while allowing future stages to plug in persistent backends
without rewriting domain or API code.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from app.incidents.models import Incident


class IncidentRepository(ABC):
    """Abstract contract for incident storage operations."""

    @abstractmethod
    def create(self, incident: Incident) -> Incident:
        """Store a newly created incident."""
        pass

    @abstractmethod
    def get_by_id(self, incident_id: str) -> Optional[Incident]:
        """Retrieve an incident by its unique identifier."""
        pass

    @abstractmethod
    def list_all(self) -> List[Incident]:
        """List all stored incidents."""
        pass

    @abstractmethod
    def update(self, incident: Incident) -> Incident:
        """Update an existing incident in storage."""
        pass


class InMemoryIncidentRepository(IncidentRepository):
    """In-memory implementation of IncidentRepository using a private dictionary."""

    def __init__(self) -> None:
        self._storage: Dict[str, Incident] = {}

    def create(self, incident: Incident) -> Incident:
        self._storage[incident.id] = incident
        return incident

    def get_by_id(self, incident_id: str) -> Optional[Incident]:
        return self._storage.get(incident_id)

    def list_all(self) -> List[Incident]:
        return list(self._storage.values())

    def update(self, incident: Incident) -> Incident:
        self._storage[incident.id] = incident
        return incident

    def clear(self) -> None:
        """Reset internal storage. Reserved strictly for test isolation."""
        self._storage.clear()
