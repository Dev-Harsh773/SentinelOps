"""Remediation branch repository abstractions and in-memory implementation."""

from abc import ABC, abstractmethod
import threading
from typing import Dict, Optional

from app.remediation.models import RemediationBranch


class RemediationBranchRepository(ABC):
    """Abstract interface for persisting and querying isolated remediation branches."""

    @abstractmethod
    def save(self, branch: RemediationBranch) -> RemediationBranch:
        """Persist a remediation branch record."""
        ...

    @abstractmethod
    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationBranch]:
        """Retrieve the branch record associated with an incident."""
        ...

    @abstractmethod
    def get_by_remediation_id(self, remediation_id: str) -> Optional[RemediationBranch]:
        """Retrieve the branch record associated with a specific remediation proposal."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Clear all stored branches (used in test isolation)."""
        ...


class InMemoryRemediationBranchRepository(RemediationBranchRepository):
    """Thread-safe in-memory implementation of RemediationBranchRepository."""

    def __init__(self) -> None:
        self._branches: Dict[str, RemediationBranch] = {}
        self._incident_index: Dict[str, str] = {}
        self._remediation_index: Dict[str, str] = {}
        self._lock = threading.Lock()

    def save(self, branch: RemediationBranch) -> RemediationBranch:
        with self._lock:
            self._branches[branch.branch_id] = branch
            self._incident_index[branch.incident_id] = branch.branch_id
            self._remediation_index[branch.remediation_id] = branch.branch_id
            return branch

    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationBranch]:
        with self._lock:
            b_id = self._incident_index.get(incident_id)
            if not b_id:
                return None
            return self._branches.get(b_id)

    def get_by_remediation_id(self, remediation_id: str) -> Optional[RemediationBranch]:
        with self._lock:
            b_id = self._remediation_index.get(remediation_id)
            if not b_id:
                return None
            return self._branches.get(b_id)

    def clear(self) -> None:
        with self._lock:
            self._branches.clear()
            self._incident_index.clear()
            self._remediation_index.clear()
