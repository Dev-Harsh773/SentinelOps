"""Remediation repository abstractions and in-memory implementation."""

import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from app.remediation.models import RemediationProposal


class RemediationRepository(ABC):
    """Abstract interface for storing and querying remediation proposals."""

    @abstractmethod
    def save(self, proposal: RemediationProposal) -> RemediationProposal:
        """Persist or update a remediation proposal."""
        ...

    @abstractmethod
    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationProposal]:
        """Retrieve the active remediation proposal for an incident."""
        ...

    @abstractmethod
    def get_by_id(self, remediation_id: str) -> Optional[RemediationProposal]:
        """Retrieve a remediation proposal by its unique ID."""
        ...

    @abstractmethod
    def list_all(self) -> List[RemediationProposal]:
        """List all stored remediation proposals."""
        ...

    @abstractmethod
    def delete_by_incident_id(self, incident_id: str) -> bool:
        """Delete remediation proposal for an incident if present."""
        ...


class InMemoryRemediationRepository(RemediationRepository):
    """Thread-safe in-memory implementation maintaining single active proposal per incident."""

    def __init__(self) -> None:
        self._storage: Dict[str, RemediationProposal] = {}
        self._incident_index: Dict[str, str] = {}
        self._lock = threading.Lock()

    def save(self, proposal: RemediationProposal) -> RemediationProposal:
        with self._lock:
            # If replacing an existing proposal for the incident with a new remediation_id, remove old
            old_rem_id = self._incident_index.get(proposal.incident_id)
            if old_rem_id and old_rem_id != proposal.remediation_id:
                self._storage.pop(old_rem_id, None)

            self._storage[proposal.remediation_id] = proposal
            self._incident_index[proposal.incident_id] = proposal.remediation_id
            return proposal

    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationProposal]:
        with self._lock:
            rem_id = self._incident_index.get(incident_id)
            if not rem_id:
                return None
            return self._storage.get(rem_id)

    def get_by_id(self, remediation_id: str) -> Optional[RemediationProposal]:
        with self._lock:
            return self._storage.get(remediation_id)

    def list_all(self) -> List[RemediationProposal]:
        with self._lock:
            return list(self._storage.values())

    def delete_by_incident_id(self, incident_id: str) -> bool:
        with self._lock:
            rem_id = self._incident_index.pop(incident_id, None)
            if rem_id:
                self._storage.pop(rem_id, None)
                return True
            return False

    def clear(self) -> None:
        """Clear all stored proposals (used in test isolation)."""
        with self._lock:
            self._storage.clear()
            self._incident_index.clear()
