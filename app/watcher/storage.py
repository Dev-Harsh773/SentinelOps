"""SQLite local persistence store for Sentinel Watcher telemetry.

Provides durable, local SQLite storage for continuous telemetry events,
with indexed lookups and dual-bounded retention pruning (time-based and count-based).
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

from app.watcher.models import SignalType, TelemetryEvent

logger = logging.getLogger("sentinelops.watcher.storage")


class SqliteTelemetryStore:
    """Manages SQLite persistence for TelemetryEvent records."""

    def __init__(self, db_path: str = "runtime/sentinelops.db") -> None:
        self._db_path = db_path
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _init_db(self) -> None:
        """Create tables and performance indices if they do not exist."""
        cursor = self._conn.cursor()
        if self._db_path != ":memory:":
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_events (
                event_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                service TEXT NOT NULL,
                environment TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                source TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                level TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                request_id TEXT,
                trace_id TEXT,
                endpoint TEXT,
                status_code INTEGER,
                exception_type TEXT,
                metadata_json TEXT NOT NULL
            );
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp ON telemetry_events (timestamp DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_request_id ON telemetry_events (request_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_project_service ON telemetry_events (project_id, service);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_signal_level ON telemetry_events (signal_type, level);")
        self._conn.commit()

    def save(self, event: TelemetryEvent) -> None:
        """Persist a single TelemetryEvent."""
        self.save_batch([event])

    def save_batch(self, events: List[TelemetryEvent]) -> None:
        """Persist multiple TelemetryEvent instances atomically."""
        if not events:
            return

        query = """
            INSERT OR REPLACE INTO telemetry_events (
                event_id, project_id, service, environment, signal_type,
                source, timestamp, ingested_at, level, event_type,
                message, request_id, trace_id, endpoint, status_code,
                exception_type, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                e.event_id,
                e.project_id,
                e.service,
                e.environment,
                e.signal_type.value,
                e.source,
                e.timestamp.isoformat(),
                e.ingested_at.isoformat(),
                e.level,
                e.event_type,
                e.message,
                e.request_id,
                e.trace_id,
                e.endpoint,
                e.status_code,
                e.exception_type,
                json.dumps(e.metadata),
            )
            for e in events
        ]
        cursor = self._conn.cursor()
        cursor.executemany(query, rows)
        self._conn.commit()

    def get_by_id(self, event_id: str) -> Optional[TelemetryEvent]:
        """Retrieve a specific TelemetryEvent by event_id."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM telemetry_events WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_event(row)

    def query(
        self,
        limit: int = 50,
        signal_type: Optional[SignalType] = None,
        level: Optional[str] = None,
        service: Optional[str] = None,
        project_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> List[TelemetryEvent]:
        """Query stored events with optional filtering, ordered newest first."""
        conditions = []
        params = []

        if signal_type:
            conditions.append("signal_type = ?")
            params.append(signal_type.value)
        if level:
            conditions.append("level = ?")
            params.append(level.upper())
        if service:
            conditions.append("service = ?")
            params.append(service)
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if request_id:
            conditions.append("request_id = ?")
            params.append(request_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM telemetry_events {where_clause} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return [self._row_to_event(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Return the total number of stored events."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM telemetry_events")
        return cursor.fetchone()[0]

    def prune(self, max_events: Optional[int] = None, retention_hours: Optional[int] = None) -> int:
        """Prune stored events based on retention window and maximum count.

        Returns total number of deleted rows.
        """
        deleted_count = 0
        cursor = self._conn.cursor()

        # Time-based retention pruning
        if retention_hours and retention_hours > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
            cutoff_iso = cutoff.isoformat()
            cursor.execute("DELETE FROM telemetry_events WHERE timestamp < ?", (cutoff_iso,))
            deleted_count += cursor.rowcount

        # Count-based capacity capping
        if max_events and max_events > 0:
            total = self.count()
            if total > max_events:
                excess = total - max_events
                cursor.execute(
                    """
                    DELETE FROM telemetry_events WHERE event_id IN (
                        SELECT event_id FROM telemetry_events ORDER BY timestamp ASC LIMIT ?
                    )
                    """,
                    (excess,),
                )
                deleted_count += cursor.rowcount

        if deleted_count > 0:
            self._conn.commit()
            logger.info("Pruned %d events from telemetry storage", deleted_count)

        return deleted_count

    def close(self) -> None:
        """Close SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    def _row_to_event(self, row: sqlite3.Row) -> TelemetryEvent:
        """Helper to convert a sqlite3.Row to TelemetryEvent."""
        return TelemetryEvent(
            event_id=row["event_id"],
            project_id=row["project_id"],
            service=row["service"],
            environment=row["environment"],
            signal_type=SignalType(row["signal_type"]),
            source=row["source"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            ingested_at=datetime.fromisoformat(row["ingested_at"]),
            level=row["level"],
            event_type=row["event_type"],
            message=row["message"],
            request_id=row["request_id"],
            trace_id=row["trace_id"],
            endpoint=row["endpoint"],
            status_code=row["status_code"],
            exception_type=row["exception_type"],
            metadata=json.loads(row["metadata_json"]),
        )
