"""Dependency injection providers for SentinelOps retrieval module."""

from app.common.config import config
from app.retrieval.index import CodeIndex
from app.retrieval.service import RetrievalService

# Shared in-memory index singleton across application lifetime
_shared_code_index = CodeIndex()


def get_code_index() -> CodeIndex:
    """Provides access to the shared in-memory code index."""
    return _shared_code_index


def get_retrieval_service() -> RetrievalService:
    """Provides RetrievalService wired with shared index and configuration."""
    return RetrievalService(
        index=_shared_code_index,
        default_repo_path=config.source_repository_path,
    )
