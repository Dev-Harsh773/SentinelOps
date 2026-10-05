"""Evidence repository interface and in-memory implementation.

Keeps Evidence storage separate from the Incident repository while providing
clean interface boundaries for future database persistence.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set
from app.telemetry.models import Evidence


class EvidenceRepository(ABC):
    """Abstract contract for evidence persistence."""

    @abstractmethod
    def create(self, evidence: Evidence) -> Evidence:
        """Persist a new evidence record."""
        pass

    @abstractmethod
    def list_for_incident(self, incident_id: str) -> List[Evidence]:
        """List all evidence attached to a specific incident."""
        pass

    @abstractmethod
    def get_by_id(self, evidence_id: str) -> Optional[Evidence]:
        """Retrieve a specific evidence item by its ID."""
        pass

    @abstractmethod
    def get_fingerprints_for_incident(self, incident_id: str) -> Set[str]:
        """Return all fingerprints of evidence already attached to an incident."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Reset repository storage. Reserved strictly for test isolation."""
        pass


class InMemoryEvidenceRepository(EvidenceRepository):
    """In-memory implementation of EvidenceRepository."""

    def __init__(self) -> None:
        self._storage: Dict[str, Evidence] = {}

    def create(self, evidence: Evidence) -> Evidence:
        self._storage[evidence.id] = evidence
        return evidence

    def list_for_incident(self, incident_id: str) -> List[Evidence]:
        return [e for e in self._storage.values() if e.incident_id == incident_id]

    def get_by_id(self, evidence_id: str) -> Optional[Evidence]:
        return self._storage.get(evidence_id)

    def get_fingerprints_for_incident(self, incident_id: str) -> Set[str]:
        return {e.fingerprint() for e in self.list_for_incident(incident_id)}

    def clear(self) -> None:
        self._storage.clear()


class SqliteEvidenceRepository(EvidenceRepository):
    """SQLite-backed durable persistence store for Evidence records."""

    def __init__(self, db_path: str = "runtime/sentinelops.db") -> None:
        import json
        import os
        from pathlib import Path
        import sqlite3
        import threading
        from app.telemetry.models import EvidenceType

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
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                type TEXT NOT NULL,
                source TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                service TEXT NOT NULL,
                level TEXT NOT NULL,
                event TEXT NOT NULL,
                message TEXT NOT NULL,
                endpoint TEXT,
                exception_type TEXT,
                created_at TEXT NOT NULL,
                request_id TEXT,
                trace_id TEXT,
                metadata_json TEXT
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_incident_id ON evidence(incident_id);"
        )
        self._conn.commit()

    def _row_to_evidence(self, row: Any) -> Evidence:
        import json
        from datetime import datetime
        from app.telemetry.models import EvidenceType

        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        return Evidence(
            id=row["id"],
            incident_id=row["incident_id"],
            type=EvidenceType(row["type"]),
            source=row["source"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            service=row["service"],
            level=row["level"],
            event=row["event"],
            message=row["message"],
            endpoint=row["endpoint"],
            exception_type=row["exception_type"],
            created_at=datetime.fromisoformat(row["created_at"]),
            request_id=row["request_id"],
            trace_id=row["trace_id"],
            metadata=meta,
        )

    def create(self, evidence: Evidence) -> Evidence:
        import json

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO evidence (
                    id, incident_id, type, source, timestamp, service, level,
                    event, message, endpoint, exception_type, created_at,
                    request_id, trace_id, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    evidence.id,
                    evidence.incident_id,
                    evidence.type.value if hasattr(evidence.type, "value") else str(evidence.type),
                    evidence.source,
                    evidence.timestamp.isoformat() if hasattr(evidence.timestamp, "isoformat") else str(evidence.timestamp),
                    evidence.service,
                    evidence.level,
                    evidence.event,
                    evidence.message,
                    evidence.endpoint,
                    evidence.exception_type,
                    evidence.created_at.isoformat() if hasattr(evidence.created_at, "isoformat") else str(evidence.created_at),
                    evidence.request_id,
                    evidence.trace_id,
                    json.dumps(evidence.metadata) if evidence.metadata else None,
                ),
            )
            self._conn.commit()
            return evidence

    def list_for_incident(self, incident_id: str) -> List[Evidence]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM evidence WHERE incident_id = ? ORDER BY timestamp ASC, created_at ASC;",
                (incident_id,),
            )
            return [self._row_to_evidence(r) for r in cursor.fetchall()]

    def get_by_id(self, evidence_id: str) -> Optional[Evidence]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM evidence WHERE id = ?;", (evidence_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_evidence(row)

    def get_fingerprints_for_incident(self, incident_id: str) -> Set[str]:
        items = self.list_for_incident(incident_id)
        return {e.fingerprint() for e in items}

    def clear(self) -> None:
        """Reset repository storage. Guarded against production DB deletion."""
        from pathlib import Path
        prod_path = str(Path("runtime/sentinelops.db").resolve())
        if self._db_path != ":memory:" and Path(self._db_path).resolve() == Path(prod_path):
            raise RuntimeError(
                f"Refusing to clear production evidence database at {self._db_path}"
            )
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM evidence;")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
