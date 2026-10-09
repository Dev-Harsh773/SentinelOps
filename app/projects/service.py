from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, List, Optional
import uuid

if TYPE_CHECKING:
    from app.knowledge.service import ProjectKnowledgeService
from app.common import config as config_module
from app.projects.models import Project, ProjectStatus
from app.projects.schemas import (
    GitHubProjectRegisterRequest,
    ProjectReadinessResponse,
    ProjectRegisterRequest,
)
from app.projects.storage import (
    DuplicateProjectIdError,
    DuplicateWorkspacePathError,
    ProjectHasActiveConnectorsError,
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

    def _generate_project_id(self, name: str) -> str:
        """Deterministically derive a unique, URL-safe project_id from display name.

        e.g., 'Order Service' -> 'order-service', duplicate -> 'order-service-2', next -> 'order-service-3'.
        """
        base_slug = re.sub(r"[^a-zA-Z0-9_\-\.]+", "-", name.strip().lower()).strip("-.")
        if not base_slug:
            base_slug = "project"
        candidate = base_slug
        counter = 2
        while self._project_store.get_project(candidate):
            candidate = f"{base_slug}-{counter}"
            counter += 1
        return candidate

    def register_project(self, request: ProjectRegisterRequest) -> Project:
        """Validate workspace, register project, and execute initial indexing."""
        raw_path = request.workspace_path.strip()

        # Step 1: Resolve canonical and OS-aware normalized paths
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

        # Step 3: Establish unique project_id
        project_id = request.project_id or self._generate_project_id(request.name)
        if request.project_id and self._project_store.get_project(request.project_id):
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
            project_id=project_id,
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
            self._knowledge_service.index_project_initial(project_id)
            return self._project_store.get_project(project_id) or project
        except Exception as exc:
            logger.error("Initial indexing failed for project '%s': %s", project_id, exc)
            raise ProjectOnboardingError(str(exc)) from exc

    def register_github_project(self, request: GitHubProjectRegisterRequest) -> Project:
        """Atomically clone a public GitHub repository into a managed workspace and onboard project."""
        from app.common.security import (
            GitArgumentValidator,
            GitURLValidator,
            get_managed_workspaces_root,
        )

        # Step 1: Validate repository URL and optional branch
        validated_url = GitURLValidator.validate_github_https_url(request.repo_url)
        validated_branch: Optional[str] = None
        if request.branch:
            validated_branch = GitArgumentValidator.validate_branch_name(request.branch)

        # Step 2: Allocate an isolated per-operation staging directory
        managed_root = get_managed_workspaces_root()
        staging_root = managed_root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)

        staging_dir: Optional[Path] = None
        for _ in range(5):
            op_id = uuid.uuid4().hex
            candidate_staging = staging_root / op_id
            try:
                candidate_staging.mkdir(parents=True, exist_ok=False)
                staging_dir = candidate_staging
                break
            except FileExistsError:
                continue

        if staging_dir is None:
            raise ProjectOnboardingError("Failed to allocate an isolated staging directory for Git clone.")

        # Step 3: Execute git clone with hardened grammar strictly into the staging directory
        cmd = ["git", "clone", "--depth", "1", "--single-branch"]
        if validated_branch:
            cmd.extend(["--branch", validated_branch])
        cmd.extend(["--", validated_url, str(staging_dir)])

        try:
            res = subprocess.run(
                cmd,
                shell=False,
                timeout=60,
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                shutil.rmtree(staging_dir, ignore_errors=True)
                err_detail = res.stderr.strip() or f"git clone exited with code {res.returncode}"
                logger.error("Git clone failed for '%s': %s", validated_url, err_detail)
                raise ProjectOnboardingError(f"Git clone failed: {err_detail}")
        except subprocess.TimeoutExpired as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            logger.error("Git clone timed out after 60s for '%s'", validated_url)
            raise ProjectOnboardingError("Git clone timed out after 60 seconds") from exc
        except Exception as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            if isinstance(exc, ProjectOnboardingError):
                raise
            raise ProjectOnboardingError(f"Git clone error: {exc}") from exc

        # Step 4: Deterministic reservation loop (unique project_id and final workspace directory)
        base_slug = re.sub(r"[^a-zA-Z0-9_\-\.]+", "-", request.name.strip().lower()).strip("-.")
        if not base_slug:
            base_slug = "project"

        final_dir: Optional[Path] = None
        claimed_project_id: Optional[str] = None
        project_obj: Optional[Project] = None

        def _candidate_generator():
            if request.project_id:
                yield request.project_id
                return
            yield base_slug
            idx = 2
            while True:
                yield f"{base_slug}-{idx}"
                idx += 1

        for candidate_id in _candidate_generator():
            target_final = managed_root / candidate_id
            if self._project_store.get_project(candidate_id) or target_final.exists():
                if request.project_id:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                    raise DuplicateProjectIdError(request.project_id)
                continue

            try:
                staging_dir.rename(target_final)
                final_dir = target_final
            except (FileExistsError, OSError):
                if request.project_id:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                    raise DuplicateProjectIdError(request.project_id)
                continue

            # Detect git branch on cloned directory
            is_git = True
            default_branch = validated_branch or "main"
            try:
                client = GitClient(repository_path=str(final_dir), timeout_seconds=5)
                code, stdout, _ = client._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
                if code == 0:
                    branch_out = stdout.strip()
                    if branch_out and branch_out != "HEAD":
                        default_branch = branch_out
            except Exception:
                pass

            now = datetime.now(timezone.utc)
            canonical_path = final_dir.resolve().as_posix()
            normalized_path = os.path.normcase(os.path.normpath(str(final_dir.resolve())))

            project_obj = Project(
                project_id=candidate_id,
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

            try:
                self._project_store.create_project(project_obj)
                claimed_project_id = candidate_id
                break
            except (DuplicateProjectIdError, DuplicateWorkspacePathError):
                try:
                    final_dir.rename(staging_dir)
                except Exception:
                    pass
                final_dir = None
                if request.project_id:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                    raise DuplicateProjectIdError(request.project_id)
                continue

        if not claimed_project_id or not final_dir or not project_obj:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise ProjectOnboardingError("Failed to atomically reserve a unique project ID and workspace.")

        # Step 5: Initial indexing with failure rollback
        try:
            self._knowledge_service.index_project_initial(claimed_project_id)
            return self._project_store.get_project(claimed_project_id) or project_obj
        except Exception as exc:
            logger.error("Initial indexing failed for GitHub project '%s': %s; rolling back", claimed_project_id, exc)
            self._project_store.delete_project(claimed_project_id)
            shutil.rmtree(final_dir, ignore_errors=True)
            raise ProjectOnboardingError(str(exc)) from exc

    def get_project_readiness(
        self,
        project_id: str,
        connector_store: Any,
        telemetry_store: Any,
    ) -> ProjectReadinessResponse:
        """Calculate live operational readiness and connection recency for an onboarded project."""
        from app.connectors.models import ConnectorStatus, ConnectorType, TargetStatus

        project = self.get_project(project_id)

        source_connected = Path(project.workspace_path).is_dir()
        is_indexed = False
        try:
            snapshot = self._knowledge_service.get_project_knowledge(project_id)
            if snapshot and snapshot.files_count > 0 and project.status == ProjectStatus.READY:
                is_indexed = True
            elif project.status == ProjectStatus.READY and project.last_indexed_at is not None:
                is_indexed = True
        except Exception:
            is_indexed = project.status == ProjectStatus.READY and project.last_indexed_at is not None

        connectors = connector_store.list_connectors(project_id=project_id)
        connectors_count = len(connectors)
        active_connectors = [c for c in connectors if c.status == ConnectorStatus.ACTIVE]
        active_connectors_count = len(active_connectors)

        health_status: Optional[str] = None
        active_pollers = [c for c in active_connectors if c.connector_type == ConnectorType.HTTP_POLLER]
        if active_pollers:
            statuses = []
            for p in active_pollers:
                h = connector_store.get_health(p.connector_id)
                if h:
                    statuses.append(h.target_status)
            if TargetStatus.UNHEALTHY in statuses:
                health_status = "unhealthy"
            elif TargetStatus.HEALTHY in statuses:
                health_status = "healthy"
            else:
                health_status = "unknown"

        cursor = telemetry_store._conn.cursor()
        cursor.execute(
            "SELECT MAX(timestamp) FROM telemetry_events WHERE project_id = ?",
            (project_id,),
        )
        row = cursor.fetchone()
        last_telemetry_at: Optional[datetime] = None
        if row and row[0]:
            try:
                raw_ts = row[0]
                if isinstance(raw_ts, str):
                    if raw_ts.endswith("Z"):
                        raw_ts = raw_ts[:-1] + "+00:00"
                    last_telemetry_at = datetime.fromisoformat(raw_ts)
                    if last_telemetry_at.tzinfo is None:
                        last_telemetry_at = last_telemetry_at.replace(tzinfo=timezone.utc)
                elif isinstance(raw_ts, datetime):
                    last_telemetry_at = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=timezone.utc)
            except Exception as e:
                logger.debug("Failed parsing last_telemetry_at '%s': %s", row[0], e)

        recency_window = config_module.config.telemetry_recency_window_seconds
        now = datetime.now(timezone.utc)
        telemetry_receiving = False
        if last_telemetry_at:
            telemetry_receiving = (now - last_telemetry_at).total_seconds() <= recency_window

        has_webhook = any(c.connector_type == ConnectorType.WEBHOOK for c in active_connectors)
        external_webhook_ready = bool(config_module.config.public_ingress_url) if has_webhook else True

        return ProjectReadinessResponse(
            project_id=project.project_id,
            project_status=project.status,
            is_indexed=is_indexed,
            source_connected=source_connected,
            connectors_count=connectors_count,
            active_connectors_count=active_connectors_count,
            health_status=health_status,
            last_telemetry_at=last_telemetry_at,
            telemetry_receiving=telemetry_receiving,
            recency_window_seconds=recency_window,
            external_webhook_ready=external_webhook_ready,
        )

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
