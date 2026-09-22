"""Git change intelligence and repository inspection module for SentinelOps."""

from app.repository.client import GitClient
from app.repository.models import (
    ChangedFile,
    CommitDetails,
    CommitDiff,
    GitCommandError,
    GitCommit,
    GitCommitNotFoundError,
    GitCommitReferenceInvalidError,
    GitFilePathInvalidError,
    GitLimitInvalidError,
    GitRepositoryInvalidError,
    GitRepositoryNotFoundError,
)
from app.repository.service import GitService

__all__ = [
    "GitClient",
    "GitService",
    "GitCommit",
    "ChangedFile",
    "CommitDetails",
    "CommitDiff",
    "GitRepositoryNotFoundError",
    "GitRepositoryInvalidError",
    "GitCommitNotFoundError",
    "GitCommitReferenceInvalidError",
    "GitFilePathInvalidError",
    "GitLimitInvalidError",
    "GitCommandError",
]
