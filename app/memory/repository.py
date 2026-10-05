"""Incident memory repository abstractions and in-memory implementation."""

import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.memory.models import IncidentMemory


class IncidentMemoryRepository(ABC):
    """Abstract interface for storing and retrieving incident memories."""

    @abstractmethod
    def save(self, memory: IncidentMemory) -> IncidentMemory:
        """Persists or updates an incident memory record."""
        ...

    @abstractmethod
    def get_by_incident_id(self, incident_id: str) -> Optional[IncidentMemory]:
        """Retrieves a memory record by its associated incident ID."""
        ...

    @abstractmethod
    def list_all(self) -> List[IncidentMemory]:
        """Returns all stored incident memory records."""
        ...


class InMemoryIncidentMemoryRepository(IncidentMemoryRepository):
    """Thread-safe in-memory repository for trusted incident memories."""

    def __init__(self) -> None:
        self._storage: Dict[str, IncidentMemory] = {}
        self._lock = threading.Lock()

    def save(self, memory: IncidentMemory) -> IncidentMemory:
        """Persist or update an incident memory record, enforcing one trusted record per incident."""
        with self._lock:
            self._storage[memory.incident_id] = memory
            return memory

    def get_by_incident_id(self, incident_id: str) -> Optional[IncidentMemory]:
        """Look up an incident memory by incident ID."""
        with self._lock:
            return self._storage.get(incident_id)

    def list_all(self) -> List[IncidentMemory]:
        """Return a copy of all stored incident memories."""
        with self._lock:
            return list(self._storage.values())

    def clear(self) -> None:
        """Clear all stored memories (useful for testing)."""
        with self._lock:
            self._storage.clear()


class SqliteIncidentMemoryRepository(IncidentMemoryRepository):
    """SQLite-backed storage for trusted incident memories."""

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
            CREATE TABLE IF NOT EXISTS incident_memories (
                incident_id TEXT PRIMARY KEY,
                service TEXT NOT NULL,
                environment TEXT NOT NULL,
                title TEXT NOT NULL,
                failure_location TEXT NOT NULL,
                triggering_condition TEXT NOT NULL,
                root_cause_hypothesis TEXT NOT NULL,
                summary TEXT NOT NULL,
                endpoint TEXT,
                exception_type TEXT,
                relevant_symbols_json TEXT,
                relevant_files_json TEXT,
                resolution_notes TEXT,
                investigation_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_service ON incident_memories(service);"
        )
        self._conn.commit()

    def _row_to_memory(self, row: Any) -> IncidentMemory:
        from datetime import datetime
        import json
        from app.memory.models import IncidentMemory

        return IncidentMemory(
            incident_id=row["incident_id"],
            service=row["service"],
            environment=row["environment"],
            title=row["title"],
            failure_location=row["failure_location"],
            triggering_condition=row["triggering_condition"],
            root_cause_hypothesis=row["root_cause_hypothesis"],
            summary=row["summary"],
            endpoint=row["endpoint"],
            exception_type=row["exception_type"],
            relevant_symbols=json.loads(row["relevant_symbols_json"]) if row["relevant_symbols_json"] else [],
            relevant_files=json.loads(row["relevant_files_json"]) if row["relevant_files_json"] else [],
            resolution_notes=row["resolution_notes"],
            investigation_id=row["investigation_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def save(self, memory: IncidentMemory) -> IncidentMemory:
        import json

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO incident_memories (
                    incident_id, service, environment, title, failure_location,
                    triggering_condition, root_cause_hypothesis, summary, endpoint,
                    exception_type, relevant_symbols_json, relevant_files_json,
                    resolution_notes, investigation_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    service=excluded.service,
                    environment=excluded.environment,
                    title=excluded.title,
                    failure_location=excluded.failure_location,
                    triggering_condition=excluded.triggering_condition,
                    root_cause_hypothesis=excluded.root_cause_hypothesis,
                    summary=excluded.summary,
                    endpoint=excluded.endpoint,
                    exception_type=excluded.exception_type,
                    relevant_symbols_json=excluded.relevant_symbols_json,
                    relevant_files_json=excluded.relevant_files_json,
                    resolution_notes=excluded.resolution_notes,
                    investigation_id=excluded.investigation_id,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at;
                """,
                (
                    memory.incident_id,
                    memory.service,
                    memory.environment,
                    memory.title,
                    memory.failure_location,
                    memory.triggering_condition,
                    memory.root_cause_hypothesis,
                    memory.summary,
                    memory.endpoint,
                    memory.exception_type,
                    json.dumps(memory.relevant_symbols),
                    json.dumps(memory.relevant_files),
                    memory.resolution_notes,
                    memory.investigation_id,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                ),
            )
            self._conn.commit()
            return memory

    def get_by_incident_id(self, incident_id: str) -> Optional[IncidentMemory]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM incident_memories WHERE incident_id = ?;",
                (incident_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_memory(row)

    def list_all(self) -> List[IncidentMemory]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM incident_memories ORDER BY created_at ASC;")
            return [self._row_to_memory(r) for r in cursor.fetchall()]

    def clear(self) -> None:
        """Clear all stored memories (used in test isolation)."""
        from pathlib import Path
        prod_path = str(Path("runtime/sentinelops.db").resolve())
        if self._db_path != ":memory:" and Path(self._db_path).resolve() == Path(prod_path):
            raise RuntimeError(
                f"Refusing to clear production memory database at {self._db_path}"
            )
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM incident_memories;")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
