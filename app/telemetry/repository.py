"""Evidence repository interface and in-memory implementation.

Keeps Evidence storage separate from the Incident repository while providing
clean interface boundaries for future database persistence.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set
from app.telemetry.models import Evidence


class EvidenceRepository(ABC):
    """Abstract contract for evidence persistence."""

    @abstractmethod
    def create(self, evidence: Evidence) -> Evidence:
        """Persist a new evidence record."""
        pass

    @abstractmethod
    def list_for_incident(self, incident_id: str) -> List[Evidence]:
        """List all evidence attached to a specific incident."""
        pass

    @abstractmethod
    def get_by_id(self, evidence_id: str) -> Optional[Evidence]:
        """Retrieve a specific evidence item by its ID."""
        pass

    @abstractmethod
    def get_fingerprints_for_incident(self, incident_id: str) -> Set[str]:
        """Return all fingerprints of evidence already attached to an incident."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Reset repository storage. Reserved strictly for test isolation."""
        pass


class InMemoryEvidenceRepository(EvidenceRepository):
    """In-memory implementation of EvidenceRepository."""

    def __init__(self) -> None:
        self._storage: Dict[str, Evidence] = {}

    def create(self, evidence: Evidence) -> Evidence:
        self._storage[evidence.id] = evidence
        return evidence

    def list_for_incident(self, incident_id: str) -> List[Evidence]:
        return [e for e in self._storage.values() if e.incident_id == incident_id]

    def get_by_id(self, evidence_id: str) -> Optional[Evidence]:
        return self._storage.get(evidence_id)

    def get_fingerprints_for_incident(self, incident_id: str) -> Set[str]:
        return {e.fingerprint() for e in self.list_for_incident(incident_id)}

    def clear(self) -> None:
        self._storage.clear()
