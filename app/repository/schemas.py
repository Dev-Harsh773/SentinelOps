"""Pydantic request and response schemas for SentinelOps Git change intelligence."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class GitCommitResponse(BaseModel):
    """Serialization model for a Git commit."""

    commit_hash: str = Field(..., description="Full 40-character hexadecimal commit hash")
    short_hash: str = Field(..., description="Abbreviated commit hash (7-12 chars)")
    author_name: str = Field(..., description="Commit author's display name")
    author_email: str = Field(..., description="Commit author's email address")
    authored_at: datetime = Field(..., description="Timestamp when original author crafted commit (UTC-aware)")
    committed_at: datetime = Field(..., description="Timestamp when committer applied commit (UTC-aware)")
    message: str = Field(..., description="Full commit message body")

    model_config = ConfigDict(from_attributes=True)


class RecentCommitsResponse(BaseModel):
    """Response container for recent commit history."""

    repository: str = Field(..., description="Logical repository identity")
    commits: List[GitCommitResponse] = Field(..., description="Ordered list of commits, newest first")

    model_config = ConfigDict(from_attributes=True)


class ChangedFileResponse(BaseModel):
    """Serialization model for a modified file within a commit."""

    file_path: str = Field(..., description="Repository-relative POSIX file path")
    change_type: str = Field(..., description="Type of change: added, modified, deleted, renamed, copied")
    old_path: Optional[str] = Field(None, description="Previous file path if renamed or copied")
    additions: Optional[int] = Field(None, description="Lines added, or null for binary/unavailable")
    deletions: Optional[int] = Field(None, description="Lines deleted, or null for binary/unavailable")

    model_config = ConfigDict(from_attributes=True)


class CommitDetailsResponse(BaseModel):
    """Response containing detailed commit metadata and changed files."""

    commit: GitCommitResponse = Field(..., description="Commit metadata")
    changed_files: List[ChangedFileResponse] = Field(..., description="List of changed file records")

    model_config = ConfigDict(from_attributes=True)


class CommitDiffResponse(BaseModel):
    """Response containing unified patch diff for a commit."""

    commit_hash: str = Field(..., description="Commit hash for which the diff was generated")
    file_path: Optional[str] = Field(None, description="Specific file path if diff was filtered")
    diff: str = Field(..., description="Unified diff patch text")
    truncated: bool = Field(..., description="True if diff output exceeded maximum size limit")

    model_config = ConfigDict(from_attributes=True)


class FileHistoryResponse(BaseModel):
    """Response container for single-file commit history."""

    file_path: str = Field(..., description="Repository-relative POSIX file path")
    commits: List[GitCommitResponse] = Field(..., description="Commits that touched this file, newest first")

    model_config = ConfigDict(from_attributes=True)
