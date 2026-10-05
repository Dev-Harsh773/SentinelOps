"""Incident repository interface, in-memory implementation, and SQLite durable persistence store.

Abstracts storage operations behind an interface so in-memory implementations can be used
in isolated tests while SqliteIncidentRepository provides production durability across process restarts.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
import os
from pathlib import Path
import sqlite3
import threading
from typing import Dict, List, Optional

from app.incidents.models import Incident, IncidentStatus, Severity


class IncidentRepository(ABC):
    """Abstract contract for incident storage operations."""

    @abstractmethod
    def create(self, incident: Incident) -> Incident:
        """Store a newly created incident."""
        pass

    @abstractmethod
    def get_by_id(self, incident_id: str) -> Optional[Incident]:
        """Retrieve an incident by its unique identifier."""
        pass

    @abstractmethod
    def list_all(self, project_id: Optional[str] = None) -> List[Incident]:
        """List all stored incidents, optionally filtered by project_id."""
        pass

    @abstractmethod
    def update(self, incident: Incident) -> Incident:
        """Update an existing incident in storage."""
        pass


class InMemoryIncidentRepository(IncidentRepository):
    """In-memory implementation of IncidentRepository using a private dictionary."""

    def __init__(self) -> None:
        self._storage: Dict[str, Incident] = {}

    def create(self, incident: Incident) -> Incident:
        self._storage[incident.id] = incident
        return incident

    def get_by_id(self, incident_id: str) -> Optional[Incident]:
        return self._storage.get(incident_id)

    def list_all(self, project_id: Optional[str] = None) -> List[Incident]:
        items = list(self._storage.values())
        if project_id:
            return [i for i in items if i.project_id == project_id]
        return items

    def update(self, incident: Incident) -> Incident:
        self._storage[incident.id] = incident
        return incident

    def clear(self) -> None:
        """Reset internal storage. Reserved strictly for test isolation."""
        self._storage.clear()


class SqliteIncidentRepository(IncidentRepository):
    """SQLite durable persistence store for Incident entities."""

    def __init__(self, db_path: str = "runtime/sentinelops.db") -> None:
        self._db_path = str(Path(db_path).resolve()) if db_path != ":memory:" else ":memory:"
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    @property
    def db_path(self) -> str:
        """Path to SQLite database file."""
        return self._db_path

    def _init_db(self) -> None:
        """Initialize incidents table and performance indices if they do not exist."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            if self._db_path != ":memory:":
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
                    status TEXT NOT NULL CHECK (status IN ('open', 'investigating', 'resolved', 'closed')),
                    service TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    project_id TEXT NOT NULL DEFAULT 'default',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_project_id ON incidents(project_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_created_at ON incidents(created_at);")
            self._conn.commit()

    @staticmethod
    def _row_to_incident(row: sqlite3.Row) -> Incident:
        """Convert a SQLite row to an Incident domain instance."""
        return Incident(
            id=row["id"],
            title=row["title"],
            summary=row["summary"],
            severity=Severity(row["severity"]),
            status=IncidentStatus(row["status"]),
            service=row["service"],
            environment=row["environment"],
            project_id=row["project_id"] if row["project_id"] is not None else "default",
            created_at=datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"],
            updated_at=datetime.fromisoformat(row["updated_at"]) if isinstance(row["updated_at"], str) else row["updated_at"],
        )

    def create(self, incident: Incident) -> Incident:
        """Store a newly created incident in SQLite."""
        sev_val = incident.severity.value if isinstance(incident.severity, Enum) else str(incident.severity)
        status_val = incident.status.value if isinstance(incident.status, Enum) else str(incident.status)
        created_str = incident.created_at.isoformat() if hasattr(incident.created_at, "isoformat") else str(incident.created_at)
        updated_str = incident.updated_at.isoformat() if hasattr(incident.updated_at, "isoformat") else str(incident.updated_at)
        project_id = incident.project_id or "default"

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO incidents (
                    id, title, summary, severity, status, service, environment, project_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    severity = excluded.severity,
                    status = excluded.status,
                    service = excluded.service,
                    environment = excluded.environment,
                    project_id = excluded.project_id,
                    updated_at = excluded.updated_at;
                """,
                (
                    incident.id,
                    incident.title,
                    incident.summary,
                    sev_val,
                    status_val,
                    incident.service,
                    incident.environment,
                    project_id,
                    created_str,
                    updated_str,
                ),
            )
            self._conn.commit()
            return incident

    def get_by_id(self, incident_id: str) -> Optional[Incident]:
        """Retrieve an incident by its unique identifier."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM incidents WHERE id = ?;", (incident_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_incident(row)

    def list_all(self, project_id: Optional[str] = None) -> List[Incident]:
        """List all stored incidents ordered chronologically, optionally filtered by project_id."""
        with self._lock:
            cursor = self._conn.cursor()
            if project_id:
                cursor.execute(
                    "SELECT * FROM incidents WHERE project_id = ? ORDER BY created_at ASC, rowid ASC;",
                    (project_id,),
                )
            else:
                cursor.execute("SELECT * FROM incidents ORDER BY created_at ASC, rowid ASC;")
            rows = cursor.fetchall()
            return [self._row_to_incident(r) for r in rows]

    def update(self, incident: Incident) -> Incident:
        """Update an existing incident in storage."""
        sev_val = incident.severity.value if isinstance(incident.severity, Enum) else str(incident.severity)
        status_val = incident.status.value if isinstance(incident.status, Enum) else str(incident.status)
        updated_str = incident.updated_at.isoformat() if hasattr(incident.updated_at, "isoformat") else str(incident.updated_at)
        project_id = incident.project_id or "default"

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                UPDATE incidents SET
                    title = ?,
                    summary = ?,
                    severity = ?,
                    status = ?,
                    service = ?,
                    environment = ?,
                    project_id = ?,
                    updated_at = ?
                WHERE id = ?;
                """,
                (
                    incident.title,
                    incident.summary,
                    sev_val,
                    status_val,
                    incident.service,
                    incident.environment,
                    project_id,
                    updated_str,
                    incident.id,
                ),
            )
            self._conn.commit()
            return incident

    def clear(self) -> None:
        """Reset internal storage. Reserved strictly for test isolation."""
        prod_path = str(Path("runtime/sentinelops.db").resolve())
        if self._db_path != ":memory:" and Path(self._db_path).resolve() == Path(prod_path):
            raise RuntimeError(
                f"Refusing to clear production incident database at {self._db_path}"
            )
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM incidents;")
            self._conn.commit()

    def close(self) -> None:
        """Close SQLite database connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
