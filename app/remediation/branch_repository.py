"""Remediation branch repository abstractions and in-memory implementation."""

from abc import ABC, abstractmethod
import threading
from typing import Any, Dict, Optional

from app.remediation.models import RemediationBranch


class RemediationBranchRepository(ABC):
    """Abstract interface for persisting and querying isolated remediation branches."""

    @abstractmethod
    def save(self, branch: RemediationBranch) -> RemediationBranch:
        """Persist a remediation branch record."""
        ...

    @abstractmethod
    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationBranch]:
        """Retrieve the branch record associated with an incident."""
        ...

    @abstractmethod
    def get_by_remediation_id(self, remediation_id: str) -> Optional[RemediationBranch]:
        """Retrieve the branch record associated with a specific remediation proposal."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Clear all stored branches (used in test isolation)."""
        ...


class InMemoryRemediationBranchRepository(RemediationBranchRepository):
    """Thread-safe in-memory implementation of RemediationBranchRepository."""

    def __init__(self) -> None:
        self._branches: Dict[str, RemediationBranch] = {}
        self._incident_index: Dict[str, str] = {}
        self._remediation_index: Dict[str, str] = {}
        self._lock = threading.Lock()

    def save(self, branch: RemediationBranch) -> RemediationBranch:
        with self._lock:
            self._branches[branch.branch_id] = branch
            self._incident_index[branch.incident_id] = branch.branch_id
            self._remediation_index[branch.remediation_id] = branch.branch_id
            return branch

    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationBranch]:
        with self._lock:
            b_id = self._incident_index.get(incident_id)
            if not b_id:
                return None
            return self._branches.get(b_id)

    def get_by_remediation_id(self, remediation_id: str) -> Optional[RemediationBranch]:
        with self._lock:
            b_id = self._remediation_index.get(remediation_id)
            if not b_id:
                return None
            return self._branches.get(b_id)

    def clear(self) -> None:
        with self._lock:
            self._branches.clear()
            self._incident_index.clear()
            self._remediation_index.clear()


class SqliteRemediationBranchRepository(RemediationBranchRepository):
    """SQLite-backed storage for isolated remediation branch metadata."""

    def __init__(self, db_path: str = "runtime/sentinelops.db") -> None:
        import os
        from pathlib import Path
        import sqlite3
        import threading

        self._db_path = str(Path(db_path).resolve()) if db_path != ":memory:" else ":memory:"
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._init_schema()

    def _init_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS remediation_branches (
                branch_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                remediation_id TEXT NOT NULL,
                approval_id TEXT NOT NULL,
                branch_name TEXT NOT NULL,
                base_branch TEXT NOT NULL,
                base_commit TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_remediation_branches_incident_id ON remediation_branches(incident_id);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_remediation_branches_rem_id ON remediation_branches(remediation_id);"
        )
        self._conn.commit()

    def _row_to_branch(self, row: Any) -> RemediationBranch:
        from datetime import datetime
        from app.remediation.models import RemediationBranch

        return RemediationBranch(
            branch_id=row["branch_id"],
            incident_id=row["incident_id"],
            remediation_id=row["remediation_id"],
            approval_id=row["approval_id"],
            branch_name=row["branch_name"],
            base_branch=row["base_branch"],
            base_commit=row["base_commit"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save(self, branch: RemediationBranch) -> RemediationBranch:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO remediation_branches (
                    branch_id, incident_id, remediation_id, approval_id,
                    branch_name, base_branch, base_commit, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(branch_id) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    remediation_id=excluded.remediation_id,
                    approval_id=excluded.approval_id,
                    branch_name=excluded.branch_name,
                    base_branch=excluded.base_branch,
                    base_commit=excluded.base_commit,
                    created_at=excluded.created_at;
                """,
                (
                    branch.branch_id,
                    branch.incident_id,
                    branch.remediation_id,
                    branch.approval_id,
                    branch.branch_name,
                    branch.base_branch,
                    branch.base_commit,
                    branch.created_at.isoformat(),
                ),
            )
            self._conn.commit()
            return branch

    def get_by_incident_id(self, incident_id: str) -> Optional[RemediationBranch]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM remediation_branches WHERE incident_id = ? ORDER BY created_at DESC LIMIT 1;",
                (incident_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_branch(row)

    def get_by_remediation_id(self, remediation_id: str) -> Optional[RemediationBranch]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM remediation_branches WHERE remediation_id = ? ORDER BY created_at DESC LIMIT 1;",
                (remediation_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_branch(row)

    def clear(self) -> None:
        """Clear all stored branches (used in test isolation)."""
        from pathlib import Path
        prod_path = str(Path("runtime/sentinelops.db").resolve())
        if self._db_path != ":memory:" and Path(self._db_path).resolve() == Path(prod_path):
            raise RuntimeError(
                f"Refusing to clear production remediation branch database at {self._db_path}"
            )
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM remediation_branches;")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
