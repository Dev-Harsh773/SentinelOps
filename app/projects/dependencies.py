"""Dependency injection providers for SentinelOps Project onboarding."""

from fastapi import Depends

from app.common.config import config
from app.knowledge.dependencies import get_project_knowledge_service
from app.knowledge.service import ProjectKnowledgeService
from app.projects.service import ProjectService
from app.projects.storage import SqliteProjectStore

_shared_project_store: SqliteProjectStore | None = None
_custom_project_db_path: str | None = None


def set_custom_project_db_path(db_path: str | None) -> None:
    """Explicitly redirect the project store to a custom DB path (used by test suites)."""
    global _custom_project_db_path, _shared_project_store
    _custom_project_db_path = db_path
    if _shared_project_store is not None:
        _shared_project_store.close()
        _shared_project_store = None


def get_project_store() -> SqliteProjectStore:
    """Provides the shared SqliteProjectStore singleton."""
    global _shared_project_store
    if _shared_project_store is None:
        db_path = _custom_project_db_path or config.project_db_path or config.watcher_db_path
        _shared_project_store = SqliteProjectStore(db_path=db_path)
    return _shared_project_store


def get_project_service(
    project_store: SqliteProjectStore = Depends(get_project_store),
    knowledge_service: ProjectKnowledgeService = Depends(get_project_knowledge_service),
) -> ProjectService:
    """Provides a fully wired ProjectService instance."""
    return ProjectService(
        project_store=project_store,
        knowledge_service=knowledge_service,
    )


def close_project_store() -> None:
    """Cleanly close and release the shared project store singleton."""
    global _shared_project_store
    if _shared_project_store is not None:
        _shared_project_store.close()
        _shared_project_store = None


def reset_project_state() -> None:
    """Reset project database for test isolation."""
    global _shared_project_store
    if _shared_project_store is not None:
        _shared_project_store.clear()
        _shared_project_store.close()
        _shared_project_store = None
