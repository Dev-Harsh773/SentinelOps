"""Repository interface and in-memory persistence for incident investigations."""

from abc import ABC, abstractmethod
from typing import Dict, Optional

from app.agents.models import Investigation


class InvestigationRepository(ABC):
    """Abstract storage interface for incident investigations."""

    @abstractmethod
    def save(self, investigation: Investigation) -> Investigation:
        """Persists an investigation record."""
        pass

    @abstractmethod
    def get_by_incident_id(self, incident_id: str) -> Optional[Investigation]:
        """Retrieves the latest investigation for a given incident ID."""
        pass

    @abstractmethod
    def get_by_id(self, investigation_id: str) -> Optional[Investigation]:
        """Retrieves an investigation by its primary ID."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clears all stored investigations (primarily for test isolation)."""
        pass


class InMemoryInvestigationRepository(InvestigationRepository):
    """In-memory implementation of InvestigationRepository."""

    def __init__(self) -> None:
        self._investigations: Dict[str, Investigation] = {}
        self._by_incident: Dict[str, str] = {}  # incident_id -> investigation_id

    def save(self, investigation: Investigation) -> Investigation:
        self._investigations[investigation.investigation_id] = investigation
        self._by_incident[investigation.incident_id] = investigation.investigation_id
        return investigation

    def get_by_incident_id(self, incident_id: str) -> Optional[Investigation]:
        inv_id = self._by_incident.get(incident_id)
        if not inv_id:
            return None
        return self._investigations.get(inv_id)

    def get_by_id(self, investigation_id: str) -> Optional[Investigation]:
        return self._investigations.get(investigation_id)

    def clear(self) -> None:
        self._investigations.clear()
        self._by_incident.clear()
