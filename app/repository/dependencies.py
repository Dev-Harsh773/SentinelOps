"""Dependency injection providers for SentinelOps Git change intelligence."""

from app.common.config import config
from app.repository.client import GitClient
from app.repository.service import GitService


def get_git_client() -> GitClient:
    """Provides a configured GitClient pointing to the configured Git repository."""
    return GitClient(repository_path=config.git_repository_path)


def get_git_service() -> GitService:
    """Provides a GitService wired with the configured client and logical repository identity."""
    return GitService(
        client=get_git_client(),
        repository_name=config.app_name,
    )
