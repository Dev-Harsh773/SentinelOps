"""Centralized dependency injection providers for Incident Memory components."""

from functools import lru_cache
import threading
from typing import Optional

from app.memory.matcher import IncidentMemoryMatcher
from app.memory.repository import (
    IncidentMemoryRepository,
    InMemoryIncidentMemoryRepository,
    SqliteIncidentMemoryRepository,
)
from app.memory.service import IncidentMemoryService

_lock = threading.RLock()
_memory_repository: Optional[IncidentMemoryRepository] = None
_custom_memory_db_path: Optional[str] = None
_shared_matcher = IncidentMemoryMatcher()


def set_custom_memory_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect memory store to custom DB path (used by test suites)."""
    global _custom_memory_db_path, _memory_repository
    with _lock:
        _custom_memory_db_path = db_path
        if _memory_repository is not None and isinstance(_memory_repository, SqliteIncidentMemoryRepository):
            _memory_repository.close()
        _memory_repository = None
        get_memory_service.cache_clear()


def get_memory_repository(db_path: Optional[str] = None) -> IncidentMemoryRepository:
    """Provide the shared incident memory repository instance."""
    global _memory_repository
    with _lock:
        if _memory_repository is None:
            resolved_db = db_path or _custom_memory_db_path or "runtime/sentinelops.db"
            _memory_repository = SqliteIncidentMemoryRepository(db_path=resolved_db)
        return _memory_repository


def close_memory_repository() -> None:
    """Closes the memory repository singleton."""
    global _memory_repository
    with _lock:
        if _memory_repository is not None and isinstance(_memory_repository, SqliteIncidentMemoryRepository):
            _memory_repository.close()
        _memory_repository = None
        get_memory_service.cache_clear()


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
    repo = get_memory_repository()
    if repo:
        repo.clear()
    get_memory_service.cache_clear()
