"""FastAPI endpoints exposing read-only Git change intelligence in SentinelOps."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.repository.dependencies import get_git_service
from app.repository.models import (
    GitCommandError,
    GitCommitNotFoundError,
    GitCommitReferenceInvalidError,
    GitFilePathInvalidError,
    GitLimitInvalidError,
    GitRepositoryInvalidError,
    GitRepositoryNotFoundError,
)
from app.repository.schemas import (
    ChangedFileResponse,
    CommitDetailsResponse,
    CommitDiffResponse,
    FileHistoryResponse,
    GitCommitResponse,
    RecentCommitsResponse,
)
from app.repository.service import GitService

router = APIRouter(prefix="/git", tags=["Git Repository"])


def _handle_domain_error(exc: Exception) -> None:
    """Translates domain exceptions to deterministic HTTP status codes."""
    if isinstance(exc, GitRepositoryNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configured Git repository is unavailable.",
        )
    if isinstance(exc, GitRepositoryInvalidError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configured path is not a valid Git repository.",
        )
    if isinstance(exc, GitCommitNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    if isinstance(exc, (GitFilePathInvalidError, GitCommitReferenceInvalidError, GitLimitInvalidError)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    if isinstance(exc, GitCommandError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Git operation failed.",
        )
    raise exc


@router.get(
    "/commits",
    response_model=RecentCommitsResponse,
    status_code=status.HTTP_200_OK,
    summary="List recent Git commits",
)
def get_recent_commits(
    limit: int = Query(10, ge=1, le=50, description="Maximum number of commits to retrieve (1-50)"),
    service: GitService = Depends(get_git_service),
) -> RecentCommitsResponse:
    """Returns the most recent repository commits, newest first."""
    try:
        repo_name, commits = service.get_recent_commits(limit=limit)
        return RecentCommitsResponse(
            repository=repo_name,
            commits=[GitCommitResponse.model_validate(c) for c in commits],
        )
    except Exception as exc:
        _handle_domain_error(exc)


@router.get(
    "/commits/{commit_hash}",
    response_model=CommitDetailsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get commit metadata and changed files",
)
def get_commit_details(
    commit_hash: str,
    service: GitService = Depends(get_git_service),
) -> CommitDetailsResponse:
    """Returns detailed metadata and changed files for a specific commit."""
    try:
        details = service.get_commit_details(commit_hash=commit_hash)
        return CommitDetailsResponse(
            commit=GitCommitResponse.model_validate(details.commit),
            changed_files=[ChangedFileResponse.model_validate(f) for f in details.changed_files],
        )
    except Exception as exc:
        _handle_domain_error(exc)


@router.get(
    "/commits/{commit_hash}/diff",
    response_model=CommitDiffResponse,
    status_code=status.HTTP_200_OK,
    summary="Get unified diff for commit or specific file",
)
def get_commit_diff(
    commit_hash: str,
    path: Optional[str] = Query(None, description="Optional repository-relative file path filter"),
    service: GitService = Depends(get_git_service),
) -> CommitDiffResponse:
    """Returns the unified patch diff for a commit, optionally filtered by file path."""
    try:
        diff_res = service.get_commit_diff(commit_hash=commit_hash, path=path)
        return CommitDiffResponse(
            commit_hash=diff_res.commit_hash,
            file_path=diff_res.file_path,
            diff=diff_res.diff,
            truncated=diff_res.truncated,
        )
    except Exception as exc:
        _handle_domain_error(exc)


@router.get(
    "/files/history",
    response_model=FileHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get commit history for a specific file",
)
def get_file_history(
    path: str = Query(..., description="Repository-relative file path"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of commits to retrieve (1-50)"),
    service: GitService = Depends(get_git_service),
) -> FileHistoryResponse:
    """Returns all commits touching a specific repository-relative file path, newest first."""
    try:
        clean_path, commits = service.get_file_history(path=path, limit=limit)
        return FileHistoryResponse(
            file_path=clean_path,
            commits=[GitCommitResponse.model_validate(c) for c in commits],
        )
    except Exception as exc:
        _handle_domain_error(exc)
