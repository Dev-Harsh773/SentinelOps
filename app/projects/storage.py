"""SQLite persistence store for SentinelOps Project definitions."""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import List, Optional

from app.projects.models import Project, ProjectStatus

logger = logging.getLogger("sentinelops.projects.storage")


class ProjectNotFoundError(Exception):
    """Raised when a requested project_id does not exist."""

    def __init__(self, project_id: str) -> None:
        super().__init__(f"Project '{project_id}' not found.")
        self.project_id = project_id


class DuplicateProjectIdError(Exception):
    """Raised when a project_id is already registered."""

    def __init__(self, project_id: str) -> None:
        super().__init__(f"Project with ID '{project_id}' is already registered.")
        self.project_id = project_id


class DuplicateWorkspacePathError(Exception):
    """Raised when a workspace path is already bound to another project."""

    def __init__(self, workspace_path: str, existing_project_id: str) -> None:
        super().__init__(
            f"Workspace path '{workspace_path}' is already registered under project '{existing_project_id}'."
        )
        self.workspace_path = workspace_path
        self.existing_project_id = existing_project_id


class ProjectHasActiveConnectorsError(Exception):
    """Raised when a project cannot be deleted because dependent connectors exist."""

    def __init__(self, project_id: str, reason: str = "") -> None:
        super().__init__(f"Cannot delete project '{project_id}': dependent records exist. {reason}".strip())
        self.project_id = project_id


class SqliteProjectStore:
    """Manages durable SQLite storage for onboarded Project entities."""

    def __init__(self, db_path: str = "runtime/sentinelops.db") -> None:
        self._db_path = str(Path(db_path).resolve()) if db_path != ":memory:" else ":memory:"
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    @property
    def db_path(self) -> str:
        """Path to SQLite database file."""
        return self._db_path

    def _init_db(self) -> None:
        """Create projects table and performance indices if they do not exist."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            if self._db_path != ":memory:":
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                workspace_path TEXT NOT NULL,
                normalized_path TEXT NOT NULL UNIQUE,
                is_git INTEGER NOT NULL,
                default_branch TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_indexed_at TEXT,
                index_version TEXT,
                error_message TEXT,
                last_index_error TEXT
            );
            """
        )
        self._conn.commit()

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        """Convert a SQLite row to a Project domain instance."""
        return Project(
            project_id=row["project_id"],
            name=row["name"],
            description=row["description"],
            workspace_path=row["workspace_path"],
            normalized_path=row["normalized_path"],
            is_git=bool(row["is_git"]),
            default_branch=row["default_branch"],
            status=ProjectStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_indexed_at=(
                datetime.fromisoformat(row["last_indexed_at"])
                if row["last_indexed_at"]
                else None
            ),
            index_version=row["index_version"],
            error_message=row["error_message"],
            last_index_error=row["last_index_error"],
        )

    def create_project(self, project: Project) -> Project:
        """Insert a new Project entity, enforcing project_id and normalized_path uniqueness."""
        with self._lock:
            # Pre-check for duplicate project_id
            if self.get_project(project.project_id):
                raise DuplicateProjectIdError(project.project_id)

            # Pre-check for duplicate normalized workspace path
            existing = self.get_project_by_normalized_path(project.normalized_path)
            if existing:
                raise DuplicateWorkspacePathError(
                    project.workspace_path, existing.project_id
                )

            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO projects (
                        project_id, name, description, workspace_path, normalized_path,
                        is_git, default_branch, status, created_at, updated_at,
                        last_indexed_at, index_version, error_message, last_index_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        project.project_id,
                        project.name,
                        project.description,
                        project.workspace_path,
                        project.normalized_path,
                        1 if project.is_git else 0,
                        project.default_branch,
                        project.status.value,
                        project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                        project.last_indexed_at.isoformat() if project.last_indexed_at else None,
                        project.index_version,
                        project.error_message,
                        project.last_index_error,
                    ),
                )
                self._conn.commit()
                return project
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                if "normalized_path" in str(exc):
                    existing = self.get_project_by_normalized_path(project.normalized_path)
                    existing_id = existing.project_id if existing else "unknown"
                    raise DuplicateWorkspacePathError(project.workspace_path, existing_id) from exc
                raise DuplicateProjectIdError(project.project_id) from exc
            except Exception:
                self._conn.rollback()
                raise

    def get_project(self, project_id: str) -> Optional[Project]:
        """Retrieve a project by project_id."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE project_id = ?;", (project_id,))
            row = cursor.fetchone()
            return self._row_to_project(row) if row else None

    def get_project_by_normalized_path(self, normalized_path: str) -> Optional[Project]:
        """Retrieve a project by normalized OS-aware workspace path."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM projects WHERE normalized_path = ?;", (normalized_path,)
            )
            row = cursor.fetchone()
            return self._row_to_project(row) if row else None

    def list_projects(self) -> List[Project]:
        """List all registered projects ordered by created_at."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM projects ORDER BY created_at ASC;")
            rows = cursor.fetchall()
            return [self._row_to_project(r) for r in rows]

    def update_project(self, project: Project) -> Project:
        """Update an existing project's mutable fields."""
        with self._lock:
            cursor = self._conn.cursor()
            now = datetime.now(timezone.utc)
            project.updated_at = now
            try:
                cursor.execute(
                    """
                    UPDATE projects SET
                        name = ?,
                        description = ?,
                        workspace_path = ?,
                        normalized_path = ?,
                        is_git = ?,
                        default_branch = ?,
                        status = ?,
                        updated_at = ?,
                        last_indexed_at = ?,
                        index_version = ?,
                        error_message = ?,
                        last_index_error = ?
                    WHERE project_id = ?;
                    """,
                    (
                        project.name,
                        project.description,
                        project.workspace_path,
                        project.normalized_path,
                        1 if project.is_git else 0,
                        project.default_branch,
                        project.status.value,
                        project.updated_at.isoformat(),
                        project.last_indexed_at.isoformat() if project.last_indexed_at else None,
                        project.index_version,
                        project.error_message,
                        project.last_index_error,
                        project.project_id,
                    ),
                )
                self._conn.commit()
                return project
            except Exception:
                self._conn.rollback()
                raise

    def delete_project(self, project_id: str) -> bool:
        """Delete a project record."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM projects WHERE project_id = ?;", (project_id,))
                self._conn.commit()
                return cursor.rowcount > 0
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise ProjectHasActiveConnectorsError(project_id, str(exc)) from exc
            except Exception:
                self._conn.rollback()
                raise

    def clear(self) -> None:
        """Remove all project records. Strictly reserved for test isolation."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM projects;")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        """Cleanly checkpoint and close the SQLite connection."""
        with self._lock:
            try:
                if self._db_path != ":memory:":
                    self._conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
