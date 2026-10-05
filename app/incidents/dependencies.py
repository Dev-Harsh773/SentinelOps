"""Centralized dependency injection providers for Incident components."""

from pathlib import Path
import threading
from typing import Optional

from app.incidents.repository import (
    IncidentRepository,
    InMemoryIncidentRepository,
    SqliteIncidentRepository,
)
from app.incidents.service import IncidentService

_lock = threading.RLock()
_incident_repository: Optional[IncidentRepository] = None
_incident_service: Optional[IncidentService] = None
_custom_incident_db_path: Optional[str] = None


def set_custom_incident_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect incident repository to a custom DB path (used by test suites)."""
    global _custom_incident_db_path, _incident_repository, _incident_service
    with _lock:
        _custom_incident_db_path = db_path
        if _incident_repository is not None:
            if hasattr(_incident_repository, "close"):
                _incident_repository.close()
            _incident_repository = None
        _incident_service = None
        try:
            from app.watcher.dependencies import reset_watcher_state
            reset_watcher_state()
        except ImportError:
            pass


def get_incident_repository(db_path: Optional[str] = None) -> IncidentRepository:
    """Provide singleton instance of SqliteIncidentRepository."""
    global _incident_repository
    with _lock:
        if _incident_repository is None:
            resolved_db = db_path or _custom_incident_db_path or "runtime/sentinelops.db"
            _incident_repository = SqliteIncidentRepository(db_path=resolved_db)
        return _incident_repository


def get_incident_service() -> IncidentService:
    """Provide singleton instance of IncidentService configured with the repository."""
    global _incident_service
    with _lock:
        if _incident_service is None:
            _incident_service = IncidentService(repository=get_incident_repository())
        return _incident_service


def close_incident_repository() -> None:
    """Close incident repository SQLite connection during shutdown."""
    global _incident_repository, _incident_service
    with _lock:
        if _incident_repository is not None:
            if hasattr(_incident_repository, "close"):
                _incident_repository.close()
            _incident_repository = None
        _incident_service = None
        try:
            from app.watcher.dependencies import reset_watcher_state
            reset_watcher_state()
        except ImportError:
            pass


def reset_incident_state(db_path: Optional[str] = None) -> None:
    """Reset incident repository and clear listeners for test isolation."""
    if db_path is not None:
        set_custom_incident_db_path(db_path)
    repo = get_incident_repository()
    prod_path = str(Path("runtime/sentinelops.db").resolve())
    if isinstance(repo, SqliteIncidentRepository) and Path(repo.db_path).resolve() == Path(prod_path):
        raise RuntimeError(
            "reset_incident_state() cannot clear production database runtime/sentinelops.db without an explicit test db_path"
        )
    if hasattr(repo, "clear"):
        repo.clear()
    service = get_incident_service()
    service.clear_listeners()
