"""SQLite storage for Connectors, Deduplication log, and Connector Health state."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import List, Optional

from app.connectors.models import (
    Connector,
    ConnectorConfig,
    ConnectorHealth,
    ConnectorStatus,
    ConnectorType,
    OperationalStatus,
    TargetStatus,
)
from app.projects.storage import ProjectNotFoundError

logger = logging.getLogger("sentinelops.connectors.store")


class ConnectorNotFoundError(Exception):
    """Raised when a connector_id does not exist."""

    def __init__(self, connector_id: str) -> None:
        super().__init__(f"Connector '{connector_id}' not found.")
        self.connector_id = connector_id


class DuplicateConnectorIdError(Exception):
    """Raised when a connector_id already exists."""

    def __init__(self, connector_id: str) -> None:
        super().__init__(f"Connector with ID '{connector_id}' is already registered.")
        self.connector_id = connector_id


class SqliteConnectorStore:
    """Manages durable SQLite persistence for Connectors in the shared metadata database."""

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
        """Initialize tables and enable foreign keys enforcement."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            if self._db_path != ":memory:":
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")

            # 0. Ensure projects table exists in shared metadata database
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

            # 1. Connectors table with ON DELETE RESTRICT on projects
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS connectors (
                    connector_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    connector_type TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE RESTRICT
                );
                """
            )

            # 2. Connector deduplication log
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_dedup_log (
                    connector_id TEXT NOT NULL,
                    external_event_id TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    PRIMARY KEY (connector_id, external_event_id),
                    FOREIGN KEY (connector_id) REFERENCES connectors(connector_id) ON DELETE CASCADE
                );
                """
            )

            # 3. Connector health state
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_health (
                    connector_id TEXT PRIMARY KEY,
                    operational_status TEXT NOT NULL,
                    target_status TEXT NOT NULL,
                    last_poll_at TEXT,
                    last_success_at TEXT,
                    consecutive_operational_errors INTEGER NOT NULL DEFAULT 0,
                    last_operational_error TEXT,
                    last_target_error TEXT,
                    FOREIGN KEY (connector_id) REFERENCES connectors(connector_id) ON DELETE CASCADE
                );
                """
            )
            self._conn.commit()

    @staticmethod
    def _row_to_connector(row: sqlite3.Row) -> Connector:
        config_data = json.loads(row["config_json"])
        return Connector(
            connector_id=row["connector_id"],
            project_id=row["project_id"],
            name=row["name"],
            connector_type=ConnectorType(row["connector_type"]),
            config=ConnectorConfig.model_validate(config_data),
            status=ConnectorStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_health(row: sqlite3.Row) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=row["connector_id"],
            operational_status=OperationalStatus(row["operational_status"]),
            target_status=TargetStatus(row["target_status"]),
            last_poll_at=datetime.fromisoformat(row["last_poll_at"]) if row["last_poll_at"] else None,
            last_success_at=datetime.fromisoformat(row["last_success_at"]) if row["last_success_at"] else None,
            consecutive_operational_errors=row["consecutive_operational_errors"],
            last_operational_error=row["last_operational_error"],
            last_target_error=row["last_target_error"],
        )

    def create_connector(self, connector: Connector) -> Connector:
        """Insert a new connector and initialize its health record."""
        with self._lock:
            # Check duplicate ID
            if self.get_connector(connector.connector_id):
                raise DuplicateConnectorIdError(connector.connector_id)

            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO connectors (
                        connector_id, project_id, name, connector_type,
                        config_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        connector.connector_id,
                        connector.project_id,
                        connector.name,
                        connector.connector_type.value,
                        json.dumps(connector.config.model_dump()),
                        connector.status.value,
                        connector.created_at.isoformat(),
                        connector.updated_at.isoformat(),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO connector_health (
                        connector_id, operational_status, target_status,
                        last_poll_at, last_success_at, consecutive_operational_errors,
                        last_operational_error, last_target_error
                    ) VALUES (?, ?, ?, NULL, NULL, 0, NULL, NULL);
                    """,
                    (
                        connector.connector_id,
                        OperationalStatus.HEALTHY.value,
                        TargetStatus.UNKNOWN.value,
                    ),
                )
                self._conn.commit()
                return connector
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                msg = str(exc).lower()
                if "foreign key" in msg:
                    raise ProjectNotFoundError(connector.project_id) from exc
                raise

    def get_connector(self, connector_id: str) -> Optional[Connector]:
        """Fetch a connector by ID."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM connectors WHERE connector_id = ?;", (connector_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_connector(row)

    def list_connectors(self, project_id: Optional[str] = None) -> List[Connector]:
        """List all connectors, optionally filtered by project_id."""
        with self._lock:
            cursor = self._conn.cursor()
            if project_id:
                cursor.execute("SELECT * FROM connectors WHERE project_id = ? ORDER BY created_at;", (project_id,))
            else:
                cursor.execute("SELECT * FROM connectors ORDER BY created_at;")
            return [self._row_to_connector(row) for row in cursor.fetchall()]

    def update_connector(self, connector: Connector) -> Connector:
        """Update an existing connector."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE connectors SET
                        name = ?,
                        config_json = ?,
                        status = ?,
                        updated_at = ?
                    WHERE connector_id = ?;
                    """,
                    (
                        connector.name,
                        json.dumps(connector.config.model_dump()),
                        connector.status.value,
                        connector.updated_at.isoformat(),
                        connector.connector_id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ConnectorNotFoundError(connector.connector_id)
                self._conn.commit()
                return connector
            except Exception:
                self._conn.rollback()
                raise

    def delete_connector(self, connector_id: str) -> bool:
        """Delete a connector and its cascading dedup and health records."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM connectors WHERE connector_id = ?;", (connector_id,))
                self._conn.commit()
                return cursor.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise

    def get_health(self, connector_id: str) -> Optional[ConnectorHealth]:
        """Fetch health record for a connector."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM connector_health WHERE connector_id = ?;", (connector_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_health(row)

    def update_health(self, health: ConnectorHealth) -> None:
        """Persist updated health diagnostics."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE connector_health SET
                        operational_status = ?,
                        target_status = ?,
                        last_poll_at = ?,
                        last_success_at = ?,
                        consecutive_operational_errors = ?,
                        last_operational_error = ?,
                        last_target_error = ?
                    WHERE connector_id = ?;
                    """,
                    (
                        health.operational_status.value,
                        health.target_status.value,
                        health.last_poll_at.isoformat() if health.last_poll_at else None,
                        health.last_success_at.isoformat() if health.last_success_at else None,
                        health.consecutive_operational_errors,
                        health.last_operational_error,
                        health.last_target_error,
                        health.connector_id,
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def has_dedup_record(self, connector_id: str, external_event_id: str) -> bool:
        """Check if an external event ID has already been successfully completed."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT 1 FROM connector_dedup_log WHERE connector_id = ? AND external_event_id = ?;",
                (connector_id, external_event_id),
            )
            return cursor.fetchone() is not None

    def record_dedup(self, connector_id: str, external_event_id: str, ingested_at: datetime) -> None:
        """Record external event ID as completed in dedup log."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO connector_dedup_log (connector_id, external_event_id, ingested_at)
                    VALUES (?, ?, ?);
                    """,
                    (connector_id, external_event_id, ingested_at.isoformat()),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def clear(self) -> None:
        """Clear all connectors and dedup entries. Strictly for test isolation."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM connector_dedup_log;")
                cursor.execute("DELETE FROM connector_health;")
                cursor.execute("DELETE FROM connectors;")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def close(self) -> None:
        """Cleanly checkpoint WAL and close connection."""
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
