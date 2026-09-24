"""Incident memory repository abstractions and in-memory implementation."""

import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from app.memory.models import IncidentMemory


class IncidentMemoryRepository(ABC):
    """Abstract interface for storing and retrieving incident memories."""

    @abstractmethod
    def save(self, memory: IncidentMemory) -> IncidentMemory:
        """Persists or updates an incident memory record."""
        ...

    @abstractmethod
    def get_by_incident_id(self, incident_id: str) -> Optional[IncidentMemory]:
        """Retrieves a memory record by its associated incident ID."""
        ...

    @abstractmethod
    def list_all(self) -> List[IncidentMemory]:
        """Returns all stored incident memory records."""
        ...


class InMemoryIncidentMemoryRepository(IncidentMemoryRepository):
    """Thread-safe in-memory repository for trusted incident memories."""

    def __init__(self) -> None:
        self._storage: Dict[str, IncidentMemory] = {}
        self._lock = threading.Lock()

    def save(self, memory: IncidentMemory) -> IncidentMemory:
        """Persist or update an incident memory record, enforcing one trusted record per incident."""
        with self._lock:
            self._storage[memory.incident_id] = memory
            return memory

    def get_by_incident_id(self, incident_id: str) -> Optional[IncidentMemory]:
        """Look up an incident memory by incident ID."""
        with self._lock:
            return self._storage.get(incident_id)

    def list_all(self) -> List[IncidentMemory]:
        """Return a copy of all stored incident memories."""
        with self._lock:
            return list(self._storage.values())

    def clear(self) -> None:
        """Clear all stored memories (useful for testing)."""
        with self._lock:
            self._storage.clear()
