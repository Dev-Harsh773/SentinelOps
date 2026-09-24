"""Centralized dependency injection providers for Incident Memory components."""

from functools import lru_cache
from app.memory.matcher import IncidentMemoryMatcher
from app.memory.repository import (
    IncidentMemoryRepository,
    InMemoryIncidentMemoryRepository,
)
from app.memory.service import IncidentMemoryService

_shared_repository = InMemoryIncidentMemoryRepository()
_shared_matcher = IncidentMemoryMatcher()


def get_memory_repository() -> IncidentMemoryRepository:
    """Provide the shared incident memory repository instance."""
    return _shared_repository


def get_memory_matcher() -> IncidentMemoryMatcher:
    """Provide the default incident memory matcher instance."""
    return _shared_matcher


@lru_cache
def get_memory_service() -> IncidentMemoryService:
    """Provide the shared incident memory service."""
    return IncidentMemoryService(
        repository=get_memory_repository(),
        matcher=get_memory_matcher(),
    )


def reset_memory_repository() -> None:
    """Resets memory repository storage for isolated testing."""
    if isinstance(_shared_repository, InMemoryIncidentMemoryRepository):
        _shared_repository.clear()
