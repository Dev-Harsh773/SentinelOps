"""Domain models and exceptions for Git change intelligence in SentinelOps."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


# =====================================================================
# Domain Exceptions
# =====================================================================


class GitRepositoryNotFoundError(Exception):
    """Raised when the configured Git repository directory does not exist."""

    def __init__(self, message: str = "Configured Git repository is unavailable."):
        super().__init__(message)


class GitRepositoryInvalidError(Exception):
    """Raised when the configured directory is not a valid Git repository."""

    def __init__(self, message: str = "Configured path is not a valid Git repository."):
        super().__init__(message)


class GitCommitNotFoundError(Exception):
    """Raised when a specific commit hash cannot be found in the repository."""

    def __init__(self, commit_hash: str):
        super().__init__(f"Commit '{commit_hash}' not found in repository.")
        self.commit_hash = commit_hash


class GitCommitReferenceInvalidError(Exception):
    """Raised when a commit hash format is malformed or invalid."""

    def __init__(self, reference: str):
        super().__init__(
            f"Invalid commit reference '{reference}'. Must be 7 to 40 hexadecimal characters."
        )
        self.reference = reference


class GitFilePathInvalidError(Exception):
    """Raised when a requested file path is invalid or attempts path traversal."""

    def __init__(self, path: str, reason: str = "Path must be a repository-relative path without traversal."):
        super().__init__(f"Invalid file path '{path}': {reason}")
        self.path = path


class GitLimitInvalidError(Exception):
    """Raised when a query limit is outside permitted bounds."""

    def __init__(self, limit: int, min_val: int = 1, max_val: int = 50):
        super().__init__(f"Limit {limit} is out of bounds. Must be between {min_val} and {max_val}.")
        self.limit = limit


class GitCommandError(Exception):
    """Raised when a read-only Git subprocess command exits with an error."""

    def __init__(self, command: str, exit_code: int, stderr: str):
        super().__init__(f"Git command failed [{exit_code}]: {command}")
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr


# =====================================================================
# Domain Data Models
# =====================================================================


@dataclass(frozen=True)
class GitCommit:
    """Represents a Git commit with metadata and timezone-aware timestamps."""

    commit_hash: str
    short_hash: str
    author_name: str
    author_email: str
    authored_at: datetime
    committed_at: datetime
    message: str


@dataclass(frozen=True)
class ChangedFile:
    """Represents a file changed in a commit."""

    file_path: str  # POSIX normalized relative path
    change_type: str  # "added", "modified", "deleted", "renamed", "copied"
    old_path: Optional[str] = None  # Previous path if renamed/copied
    additions: Optional[int] = None  # None for binary or unavailable
    deletions: Optional[int] = None  # None for binary or unavailable


@dataclass(frozen=True)
class CommitDetails:
    """Detailed view of a commit including all file modifications."""

    commit: GitCommit
    changed_files: List[ChangedFile]


@dataclass(frozen=True)
class CommitDiff:
    """Unified textual diff for a commit or specific file within a commit."""

    commit_hash: str
    file_path: Optional[str]
    diff: str
    truncated: bool
