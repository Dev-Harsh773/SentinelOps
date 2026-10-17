"""SQLite storage for notification subscriptions and durable notification records."""

from datetime import datetime, timedelta, timezone
import uuid
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.incidents.models import Severity
from app.notifications.models import (
    DeliveryStatus, DeliveryAttempt, FailureCategory,
    Notification,
    NotificationChannel,
    NotificationType,
    ReadStatus,
)
from app.projects.storage import ProjectNotFoundError

logger = logging.getLogger("sentinelops.notifications.store")


class SubscriptionNotFoundError(Exception):
    """Raised when a notification subscription does not exist."""

    def __init__(self, subscription_id: str) -> None:
        super().__init__(f"Subscription '{subscription_id}' not found.")
        self.subscription_id = subscription_id


class DuplicateSubscriptionIdError(Exception):
    """Raised when a subscription identifier already exists."""

    def __init__(self, subscription_id: str) -> None:
        super().__init__(f"Subscription with ID '{subscription_id}' is already registered.")
        self.subscription_id = subscription_id


class NotificationNotFoundError(Exception):
    """Raised when a notification record does not exist."""

    def __init__(self, notification_id: str) -> None:
        super().__init__(f"Notification '{notification_id}' not found.")
        self.notification_id = notification_id


class SqliteNotificationStore:
    """Manages durable SQLite persistence for notification subscriptions and records."""

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
        return self._db_path

    def _init_db(self) -> None:
        """Create tables, indexes, and enable foreign keys."""
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

            # 1. Subscriptions table with ON DELETE RESTRICT on projects
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    destination_config TEXT NOT NULL,
                    min_severity TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE RESTRICT
                );
                """
            )

            # 2. Notifications table (project_id stored without FK to preserve history; subscription_id ON DELETE SET NULL)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    incident_id TEXT,
                    subscription_id TEXT,
                    notification_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    delivery_config_json TEXT,
                    channel TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    delivery_status TEXT NOT NULL,
                    read_status TEXT NOT NULL DEFAULT 'unread',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_attempt_at TEXT,
                    delivered_at TEXT,
                    read_at TEXT,
                    failure_reason TEXT,
                    dedup_key TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (subscription_id) REFERENCES notification_subscriptions(subscription_id) ON DELETE SET NULL
                );
                """
            )

            # Additive migration: old Stage 22 records keep their lifecycle and budget.
            columns = {r[1] for r in cursor.execute("PRAGMA table_info(notifications)")}
            for name, definition in {
                "max_attempts": "INTEGER NOT NULL DEFAULT 3",
                "delivery_generation": "INTEGER NOT NULL DEFAULT 0",
                "claim_token": "TEXT", "lease_expires_at": "TEXT", "failure_category": "TEXT",
            }.items():
                if name not in columns:
                    cursor.execute(f"ALTER TABLE notifications ADD COLUMN {name} {definition}")
            cursor.execute("""CREATE TABLE IF NOT EXISTS notification_attempts (
                attempt_id TEXT PRIMARY KEY, notification_id TEXT NOT NULL,
                attempt_number INTEGER NOT NULL, delivery_generation INTEGER NOT NULL,
                started_at TEXT NOT NULL, dispatched_at TEXT, finished_at TEXT,
                outcome TEXT NOT NULL, response_status INTEGER, failure_category TEXT,
                failure_message TEXT, latency_ms REAL,
                UNIQUE(notification_id, delivery_generation, attempt_number),
                FOREIGN KEY(notification_id) REFERENCES notifications(notification_id) ON DELETE CASCADE
            )""")
            from app.notifications.outbox import initialize_outbox
            initialize_outbox(self._conn)

            # Indexes
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notification_subs_project ON notification_subscriptions(project_id, enabled);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_project_created ON notifications(project_id, created_at DESC);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_claim_due ON notifications(delivery_status, next_attempt_at);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_read_status ON notifications(project_id, read_status);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_dedup_key ON notifications(dedup_key);"
            )
            self._conn.commit()

    # -------------------------------------------------------------------------
    # Subscription Management
    # -------------------------------------------------------------------------

    def create_subscription(
        self,
        subscription_id: str,
        project_id: str,
        name: str,
        channel: NotificationChannel,
        destination_config: Dict[str, Any],
        min_severity: Severity,
        enabled: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> Dict[str, Any]:
        """Insert a new subscription or raise appropriate integrity errors."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO notification_subscriptions (
                        subscription_id, project_id, name, channel,
                        destination_config, min_severity, enabled,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        subscription_id,
                        project_id,
                        name,
                        channel.value,
                        json.dumps(destination_config),
                        min_severity.value,
                        1 if enabled else 0,
                        created_at.isoformat(),
                        updated_at.isoformat(),
                    ),
                )
                self._conn.commit()
                return self.get_subscription(subscription_id)
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                err_msg = str(exc).lower()
                if "foreign key" in err_msg:
                    raise ProjectNotFoundError(project_id) from exc
                if "unique" in err_msg or "primary key" in err_msg:
                    raise DuplicateSubscriptionIdError(subscription_id) from exc
                raise

    def get_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Fetch subscription by ID or raise SubscriptionNotFoundError."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT * FROM notification_subscriptions WHERE subscription_id = ?;",
                (subscription_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise SubscriptionNotFoundError(subscription_id)
            return self._row_to_subscription(row)

    def list_subscriptions(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List subscriptions optionally filtered by project_id."""
        with self._lock:
            cursor = self._conn.cursor()
            if project_id:
                cursor.execute(
                    "SELECT * FROM notification_subscriptions WHERE project_id = ? ORDER BY created_at ASC;",
                    (project_id,),
                )
            else:
                cursor.execute("SELECT * FROM notification_subscriptions ORDER BY created_at ASC;")
            return [self._row_to_subscription(r) for r in cursor.fetchall()]

    def update_subscription(
        self,
        subscription_id: str,
        name: Optional[str] = None,
        destination_config: Optional[Dict[str, Any]] = None,
        min_severity: Optional[Severity] = None,
        enabled: Optional[bool] = None,
        updated_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Update subscription fields."""
        existing = self.get_subscription(subscription_id)
        new_name = name if name is not None else existing["name"]
        new_config = destination_config if destination_config is not None else existing["destination_config"]
        new_min_severity = min_severity.value if min_severity is not None else existing["min_severity"]
        new_enabled = enabled if enabled is not None else existing["enabled"]
        up_time = (updated_at or datetime.now(timezone.utc)).isoformat()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                UPDATE notification_subscriptions SET
                    name = ?,
                    destination_config = ?,
                    min_severity = ?,
                    enabled = ?,
                    updated_at = ?
                WHERE subscription_id = ?;
                """,
                (
                    new_name,
                    json.dumps(new_config),
                    new_min_severity,
                    1 if new_enabled else 0,
                    up_time,
                    subscription_id,
                ),
            )
            self._conn.commit()
            return self.get_subscription(subscription_id)

    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete subscription by ID."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "DELETE FROM notification_subscriptions WHERE subscription_id = ?;",
                (subscription_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Notification Record Management
    # -------------------------------------------------------------------------

    def create_notification(self, notif: Notification) -> Optional[Notification]:
        """Persist a new notification record.
        
        If dedup_key violates UNIQUE constraint, returns None without raising.
        """
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO notifications (
                        notification_id, project_id, incident_id, subscription_id,
                        notification_type, severity, title, message, payload_json,
                        delivery_config_json, channel, recipient, delivery_status,
                        read_status, attempt_count, next_attempt_at, last_attempt_at,
                        delivered_at, read_at, failure_reason, dedup_key,
                        created_at, updated_at, max_attempts, delivery_generation, failure_category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        notif.notification_id,
                        notif.project_id,
                        notif.incident_id,
                        notif.subscription_id,
                        notif.notification_type.value,
                        notif.severity.value,
                        notif.title,
                        notif.message,
                        json.dumps(notif.payload),
                        json.dumps(notif.delivery_config) if notif.delivery_config else None,
                        notif.channel.value,
                        notif.recipient,
                        notif.delivery_status.value,
                        notif.read_status.value,
                        notif.attempt_count,
                        notif.next_attempt_at.isoformat() if notif.next_attempt_at else None,
                        notif.last_attempt_at.isoformat() if notif.last_attempt_at else None,
                        notif.delivered_at.isoformat() if notif.delivered_at else None,
                        notif.read_at.isoformat() if notif.read_at else None,
                        notif.failure_reason,
                        notif.dedup_key,
                        notif.created_at.isoformat(),
                        notif.updated_at.isoformat(),
                        notif.max_attempts, notif.delivery_generation,
                        notif.failure_category.value if notif.failure_category else None,
                    ),
                )
                self._conn.commit()
                logger.info("Notification queued id=%s project=%s incident=%s channel=%s status=%s",
                    notif.notification_id, notif.project_id, notif.incident_id,
                    notif.channel.value, notif.delivery_status.value)
                return notif
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                if "unique" in str(exc).lower() and "dedup_key" in str(exc).lower():
                    logger.debug("Suppressed duplicate notification key: %s", notif.dedup_key)
                    return None
                raise

    def get_notification(self, notification_id: str) -> Notification:
        """Fetch notification by ID or raise NotificationNotFoundError."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM notifications WHERE notification_id = ?;", (notification_id,))
            row = cursor.fetchone()
            if not row:
                raise NotificationNotFoundError(notification_id)
            return self._row_to_notification(row)

    def list_notifications(
        self,
        project_id: Optional[str] = None,
        read_status: Optional[ReadStatus] = None,
        channel: Optional[NotificationChannel] = None,
        delivery_status: Optional[DeliveryStatus] = None,
        limit: int = 50,
        offset: int = 0,
        incident_id: Optional[str] = None,
    ) -> List[Notification]:
        """List notifications with pagination and filtering.
        
        Does not check projects table, ensuring historical notifications
        remain visible after project deletion.
        """
        clauses = []
        params = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if incident_id:
            clauses.append("incident_id = ?")
            params.append(incident_id)
        if read_status:
            clauses.append("read_status = ?")
            params.append(read_status.value)
        if channel:
            clauses.append("channel = ?")
            params.append(channel.value)
        if delivery_status:
            clauses.append("delivery_status = ?")
            params.append(delivery_status.value)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM notifications {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(sql, params)
            return [self._row_to_notification(r) for r in cursor.fetchall()]

    def mark_notification_read(self, notification_id: str, now: datetime) -> Notification:
        """Mark single notification as read."""
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    UPDATE notifications SET
                        read_status = 'read',
                        read_at = ?,
                        updated_at = ?
                    WHERE notification_id = ?;
                    """,
                    (now.isoformat(), now.isoformat(), notification_id),
                )
                if cursor.rowcount == 0:
                    self._conn.rollback()
                    raise NotificationNotFoundError(notification_id)
                self._conn.commit()
                return self.get_notification(notification_id)
            except Exception:
                self._conn.rollback()
                raise

    def mark_all_read(self, project_id: str, now: datetime) -> int:
        """Mark all unread notifications for a project as read."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                UPDATE notifications SET
                    read_status = 'read',
                    read_at = ?,
                    updated_at = ?
                WHERE project_id = ? AND read_status = 'unread';
                """,
                (now.isoformat(), now.isoformat(), project_id),
            )
            self._conn.commit()
            return cursor.rowcount

    # -------------------------------------------------------------------------
    # Delivery Worker Claim & Lifecycle
    # -------------------------------------------------------------------------

    def claim_due_notifications(self, limit: int = 5, now: Optional[datetime] = None,
                                lease_seconds: float = 120.0) -> List[Notification]:
        """Acquire database leases and create attempts in the same write transaction."""
        if limit <= 0:
            return []
        now = now or datetime.now(timezone.utc)
        claimed = []
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            rows = self._conn.execute("""SELECT notification_id FROM notifications
                WHERE delivery_status='pending' AND channel='webhook'
                AND attempt_count < max_attempts
                AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY created_at, notification_id LIMIT ?""", (now.isoformat(), limit)).fetchall()
            for row in rows:
                token = str(uuid.uuid4())
                nid = row[0]
                self._conn.execute("""UPDATE notifications SET delivery_status='delivering',
                    attempt_count=attempt_count+1, claim_token=?, lease_expires_at=?,
                    last_attempt_at=?, next_attempt_at=NULL, updated_at=? WHERE notification_id=?""",
                    (token, (now+timedelta(seconds=lease_seconds)).isoformat(),
                     now.isoformat(), now.isoformat(), nid))
                n = self.get_notification(nid)
                self._conn.execute("""INSERT INTO notification_attempts
                    (attempt_id,notification_id,attempt_number,delivery_generation,started_at,outcome)
                    VALUES (?,?,?,?,?,'claimed')""",
                    (token,nid,n.attempt_count,n.delivery_generation,now.isoformat()))
                claimed.append(n)
        return claimed

    def begin_dispatch(self, notification_id: str, token: str, now: datetime) -> bool:
        """A claim may be dispatched once; stale or already-started callers cannot send."""
        with self._lock, self._conn:
            result = self._conn.execute("""UPDATE notification_attempts SET dispatched_at=?, outcome='sending'
                WHERE attempt_id=? AND notification_id=? AND dispatched_at IS NULL AND finished_at IS NULL
                AND EXISTS (SELECT 1 FROM notifications n WHERE n.notification_id=?
                    AND n.claim_token=? AND n.delivery_status='delivering' AND n.lease_expires_at>?)""",
                (now.isoformat(),token,notification_id,notification_id,token,now.isoformat()))
            return result.rowcount == 1

    def update_delivery_outcome(self, notification_id: str, delivery_status: DeliveryStatus,
                                next_attempt_at=None, failure_reason=None, delivered_at=None, now=None,
                                *, claim_token=None, failure_category=None, response_status=None,
                                latency_ms=None) -> bool:
        """Only the current claimed attempt can finish a delivery."""
        if delivery_status not in (DeliveryStatus.PENDING, DeliveryStatus.DELIVERED, DeliveryStatus.FAILED):
            raise ValueError("Invalid delivery outcome")
        now = now or datetime.now(timezone.utc)
        category = failure_category.value if isinstance(failure_category, FailureCategory) else failure_category
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            current = self.get_notification(notification_id)
            if not claim_token or current.claim_token != claim_token or current.delivery_status != DeliveryStatus.DELIVERING:
                return False
            self._conn.execute("""UPDATE notifications SET delivery_status=?,next_attempt_at=?,failure_reason=?,
                delivered_at=?,updated_at=?,failure_category=?,claim_token=NULL,lease_expires_at=NULL
                WHERE notification_id=?""", (delivery_status.value,
                next_attempt_at.isoformat() if next_attempt_at else None, failure_reason,
                delivered_at.isoformat() if delivered_at else None, now.isoformat(),category,notification_id))
            if claim_token:
                self._conn.execute("""UPDATE notification_attempts SET finished_at=?,outcome=?,response_status=?,
                    failure_category=?,failure_message=?,latency_ms=? WHERE attempt_id=? AND finished_at IS NULL""",
                    (now.isoformat(), 'retry_scheduled' if delivery_status == DeliveryStatus.PENDING else delivery_status.value,
                     response_status,category,failure_reason,latency_ms,claim_token))
        return True

    def pending_intents(self, limit=100):
        with self._lock:
            return [dict(r) for r in self._conn.execute(
                "SELECT * FROM notification_outbox WHERE processed_at IS NULL ORDER BY rowid LIMIT ?", (limit,))]

    def has_incident_intent(self, project_id, incident_id, status):
        with self._lock:
            return self._conn.execute("SELECT 1 FROM notification_outbox WHERE event_key=?",
                (f"{project_id}:{incident_id}:{status}",)).fetchone() is not None

    def complete_intent(self, key, now):
        with self._lock, self._conn:
            self._conn.execute("UPDATE notification_outbox SET processed_at=?, subscriptions_json='[]' WHERE event_key=? AND processed_at IS NULL",
                               (now.isoformat(),key))

    def list_attempts(self, notification_id: str) -> List[DeliveryAttempt]:
        with self._lock:
            self.get_notification(notification_id)
            rows = self._conn.execute("""SELECT * FROM notification_attempts WHERE notification_id=?
                ORDER BY delivery_generation,attempt_number""", (notification_id,)).fetchall()
            return [DeliveryAttempt(**dict(row)) for row in rows]

    def reset_for_manual_retry(self, notification_id: str, now: datetime) -> Notification:
        success, notification, _ = self.atomic_reset_failed_for_retry(notification_id, now)
        if notification is None:
            raise NotificationNotFoundError(notification_id)
        if not success:
            raise ValueError("Only failed webhook notifications can be retried")
        return notification

    def atomic_reset_failed_for_retry(self, notification_id: str, now: datetime):
        """Start a new bounded generation without erasing any attempt history."""
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            result = self._conn.execute("""UPDATE notifications SET delivery_status='pending',attempt_count=0,
                delivery_generation=delivery_generation+1,next_attempt_at=?,updated_at=?,failure_reason=NULL,
                failure_category=NULL,claim_token=NULL,lease_expires_at=NULL
                WHERE notification_id=? AND delivery_status='failed' AND channel='webhook'""",
                (now.isoformat(),now.isoformat(),notification_id))
            try:
                current = self.get_notification(notification_id)
            except NotificationNotFoundError:
                return False,None,None
            return (True,current,None) if result.rowcount else (False,current,current.delivery_status)

    def recover_in_flight_on_startup(self, now: datetime) -> int:
        """Recover expired leases only, never another worker's active delivery."""
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            rows = self._conn.execute("""SELECT * FROM notifications WHERE delivery_status='delivering'
                AND (lease_expires_at IS NULL OR lease_expires_at<=?)""", (now.isoformat(),)).fetchall()
            for row in rows:
                n = self._row_to_notification(row)
                outcome = 'pending' if n.attempt_count < n.max_attempts else 'failed'
                self._conn.execute("""UPDATE notifications SET delivery_status=?,next_attempt_at=?,updated_at=?,
                    claim_token=NULL,lease_expires_at=NULL,failure_category='interrupted',
                    failure_reason='Delivery interrupted; remote outcome unknown' WHERE notification_id=?""",
                    (outcome,now.isoformat() if outcome=='pending' else None,now.isoformat(),n.notification_id))
                self._conn.execute("""UPDATE notification_attempts SET finished_at=?,outcome='interrupted',
                    failure_category='interrupted',failure_message='Delivery interrupted; remote outcome unknown'
                    WHERE attempt_id=? AND finished_at IS NULL""", (now.isoformat(),n.claim_token))
            return len(rows)

    # -------------------------------------------------------------------------
    # Maintenance & Conversions
    # -------------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all notification tables. Strictly reserved for test isolation."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("DELETE FROM notification_outbox;")
            cursor.execute("DELETE FROM notifications;")
            cursor.execute("DELETE FROM notification_subscriptions;")
            self._conn.commit()

    def close(self) -> None:
        """Checkpoint WAL and cleanly close connection."""
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

    def _row_to_subscription(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "subscription_id": row["subscription_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "channel": NotificationChannel(row["channel"]),
            "destination_config": json.loads(row["destination_config"]),
            "min_severity": Severity(row["min_severity"]),
            "enabled": bool(row["enabled"]),
            "created_at": datetime.fromisoformat(row["created_at"]),
            "updated_at": datetime.fromisoformat(row["updated_at"]),
        }

    def _row_to_notification(self, row: sqlite3.Row) -> Notification:
        return Notification(
            notification_id=row["notification_id"],
            project_id=row["project_id"],
            incident_id=row["incident_id"],
            subscription_id=row["subscription_id"],
            notification_type=NotificationType(row["notification_type"]),
            severity=Severity(row["severity"]),
            title=row["title"],
            message=row["message"],
            payload=json.loads(row["payload_json"]),
            delivery_config=json.loads(row["delivery_config_json"]) if row["delivery_config_json"] else None,
            channel=NotificationChannel(row["channel"]),
            recipient=row["recipient"],
            delivery_status=DeliveryStatus(row["delivery_status"]),
            read_status=ReadStatus(row["read_status"]),
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"], delivery_generation=row["delivery_generation"],
            claim_token=row["claim_token"], lease_expires_at=row["lease_expires_at"],
            failure_category=row["failure_category"],
            next_attempt_at=datetime.fromisoformat(row["next_attempt_at"]) if row["next_attempt_at"] else None,
            last_attempt_at=datetime.fromisoformat(row["last_attempt_at"]) if row["last_attempt_at"] else None,
            delivered_at=datetime.fromisoformat(row["delivered_at"]) if row["delivered_at"] else None,
            read_at=datetime.fromisoformat(row["read_at"]) if row["read_at"] else None,
            failure_reason=row["failure_reason"],
            dedup_key=row["dedup_key"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
