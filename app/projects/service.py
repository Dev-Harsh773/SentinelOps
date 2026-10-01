from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.knowledge.service import ProjectKnowledgeService
from app.projects.models import Project, ProjectStatus
from app.projects.schemas import ProjectRegisterRequest
from app.projects.storage import (
    DuplicateProjectIdError,
    DuplicateWorkspacePathError,
    ProjectNotFoundError,
    SqliteProjectStore,
)
from app.repository.client import GitClient

logger = logging.getLogger("sentinelops.projects.service")


class InvalidWorkspacePathError(Exception):
    """Raised when an onboarded workspace path is invalid, inaccessible, or a root drive."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ProjectOnboardingError(Exception):
    """Raised when initial project indexing fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ProjectService:
    """Orchestrates project onboarding, workspace validation, and lifecycle operations."""

    def __init__(
        self,
        project_store: SqliteProjectStore,
        knowledge_service: ProjectKnowledgeService,
    ) -> None:
        self._project_store = project_store
        self._knowledge_service = knowledge_service

    def register_project(self, request: ProjectRegisterRequest) -> Project:
        """Validate workspace, register project, and execute initial indexing."""
        raw_path = request.workspace_path.strip()

        # Step 1: Resolve canonical and OS-aware normalized paths (Mandatory Issue 2)
        try:
            resolved = Path(raw_path).resolve()
        except Exception as exc:
            raise InvalidWorkspacePathError(f"Cannot resolve workspace path '{raw_path}': {exc}") from exc

        # Step 2: Validate directory exists and is not a filesystem root
        if not resolved.exists():
            raise InvalidWorkspacePathError(f"Workspace path does not exist: {raw_path}")
        if not resolved.is_dir():
            raise InvalidWorkspacePathError(f"Workspace path is a file, not a directory: {raw_path}")

        # Root protection check: cannot be root drive (e.g. C:\ or /)
        if len(resolved.parts) <= 1 or resolved == resolved.parent:
            raise InvalidWorkspacePathError(f"Filesystem root cannot be used as project workspace: {raw_path}")

        canonical_path = resolved.as_posix()
        normalized_path = os.path.normcase(os.path.normpath(str(resolved)))

        # Step 3: Check for duplicate project_id
        if self._project_store.get_project(request.project_id):
            raise DuplicateProjectIdError(request.project_id)

        # Step 4: Check for duplicate normalized workspace path
        existing_ws = self._project_store.get_project_by_normalized_path(normalized_path)
        if existing_ws:
            raise DuplicateWorkspacePathError(canonical_path, existing_ws.project_id)

        # Step 5: Detect Git capability
        is_git = False
        default_branch: Optional[str] = None
        git_dir = resolved / ".git"
        if git_dir.exists():
            try:
                client = GitClient(repository_path=str(resolved), timeout_seconds=5)
                code, stdout, _ = client._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
                if code == 0:
                    is_git = True
                    branch = stdout.strip()
                    default_branch = branch if branch and branch != "HEAD" else "main"
            except Exception as exc:
                logger.debug("Git detection skipped for %s: %s", raw_path, exc)
                is_git = False

        # Step 6: Create Project entity in REGISTERED status
        now = datetime.now(timezone.utc)
        project = Project(
            project_id=request.project_id,
            name=request.name,
            description=request.description,
            workspace_path=canonical_path,
            normalized_path=normalized_path,
            is_git=is_git,
            default_branch=default_branch,
            status=ProjectStatus.REGISTERED,
            created_at=now,
            updated_at=now,
        )
        self._project_store.create_project(project)

        # Step 7: Execute initial indexing
        try:
            self._knowledge_service.index_project_initial(request.project_id)
            return self._project_store.get_project(request.project_id) or project
        except Exception as exc:
            logger.error("Initial indexing failed for project '%s': %s", request.project_id, exc)
            raise ProjectOnboardingError(str(exc)) from exc

    def get_project(self, project_id: str) -> Project:
        """Retrieve project by project_id or raise ProjectNotFoundError."""
        project = self._project_store.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(project_id)
        return project

    def list_projects(self) -> List[Project]:
        """List all onboarded projects."""
        return self._project_store.list_projects()

    def delete_project(self, project_id: str) -> bool:
        """Delete an onboarded project and purge its in-memory knowledge."""
        project = self.get_project(project_id)
        deleted = self._project_store.delete_project(project_id)
        if deleted:
            with self._knowledge_service._global_lock:
                self._knowledge_service._project_indexes.pop(project_id, None)
                self._knowledge_service._project_snapshots.pop(project_id, None)
                self._knowledge_service._project_git_services.pop(project_id, None)
        return deleted
