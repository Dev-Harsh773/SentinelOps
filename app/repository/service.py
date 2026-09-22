"""Domain service orchestrating Git change intelligence in SentinelOps."""

import re
from typing import List, Optional, Tuple

from app.repository.client import GitClient
from app.repository.models import (
    CommitDetails,
    CommitDiff,
    GitCommit,
    GitCommitReferenceInvalidError,
    GitFilePathInvalidError,
    GitLimitInvalidError,
)

# Strict hexadecimal commit hash validation (7 to 40 characters)
COMMIT_HASH_REGEX = re.compile(r"^[0-9a-fA-F]{7,40}$")


def validate_commit_reference(commit_ref: str) -> str:
    """Validates that a commit reference matches 7 to 40 hex characters.

    Rejects arbitrary revision syntax (e.g. HEAD~1, branch names, tags).
    """
    cleaned = commit_ref.strip()
    if not COMMIT_HASH_REGEX.match(cleaned):
        raise GitCommitReferenceInvalidError(commit_ref)
    return cleaned.lower()


def validate_git_path(raw_path: str) -> str:
    """Validates that a path is a safe, repository-relative POSIX path.

    Enforces path traversal safety without requiring the file to currently exist on disk.
    """
    cleaned = raw_path.strip()
    if not cleaned:
        raise GitFilePathInvalidError(raw_path, "Path cannot be empty.")

    # Check for Windows drive prefixes (e.g. C:, D:)
    if len(cleaned) >= 2 and cleaned[1] == ":" and cleaned[0].isalpha():
        raise GitFilePathInvalidError(raw_path, "Absolute paths with drive letters are not allowed.")

    # Check for absolute root prefixes
    if cleaned.startswith(("/", "\\")):
        raise GitFilePathInvalidError(raw_path, "Absolute paths are not allowed.")

    normalized = cleaned.replace("\\", "/")
    parts = normalized.split("/")

    for part in parts:
        if part == "..":
            raise GitFilePathInvalidError(raw_path, "Directory traversal ('..') is not allowed.")

    clean_parts = [p for p in parts if p and p != "."]
    if not clean_parts:
        raise GitFilePathInvalidError(raw_path, "Path resolves to empty.")

    return "/".join(clean_parts)


class GitService:
    """Pure domain service for querying local Git change intelligence."""

    def __init__(self, client: GitClient, repository_name: str = "sentinelops"):
        self._client = client
        self._repository_name = repository_name

    @property
    def repository_name(self) -> str:
        """Fixed logical repository identifier."""
        return self._repository_name

    def get_recent_commits(self, limit: int = 10) -> Tuple[str, List[GitCommit]]:
        """Returns the most recent commits from the repository."""
        if not (1 <= limit <= 50):
            raise GitLimitInvalidError(limit)

        self._client.validate_repository()
        commits = self._client.get_recent_commits(limit=limit)
        return self._repository_name, commits

    def get_commit_details(self, commit_hash: str) -> CommitDetails:
        """Returns detailed commit metadata and changed file records."""
        clean_ref = validate_commit_reference(commit_hash)
        self._client.validate_repository()

        resolved_hash = self._client.resolve_commit(clean_ref)
        commit_meta = self._client.get_commit_metadata(resolved_hash)
        changed_files = self._client.get_changed_files(resolved_hash)

        return CommitDetails(commit=commit_meta, changed_files=changed_files)

    def get_commit_diff(
        self,
        commit_hash: str,
        path: Optional[str] = None,
        max_chars: int = 50000,
    ) -> CommitDiff:
        """Returns unified diff for a commit or a specific file in that commit."""
        clean_ref = validate_commit_reference(commit_hash)
        clean_path = validate_git_path(path) if path is not None else None
        self._client.validate_repository()

        resolved_hash = self._client.resolve_commit(clean_ref)
        return self._client.get_commit_diff(
            commit_hash=resolved_hash,
            path=clean_path,
            max_chars=max_chars,
        )

    def get_file_history(self, path: str, limit: int = 10) -> Tuple[str, List[GitCommit]]:
        """Returns commit history for a specific file path."""
        clean_path = validate_git_path(path)
        if not (1 <= limit <= 50):
            raise GitLimitInvalidError(limit)

        self._client.validate_repository()
        commits = self._client.get_file_history(path=clean_path, limit=limit)
        return clean_path, commits
