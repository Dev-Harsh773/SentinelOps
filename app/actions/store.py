"""SQLite storage and transactional state management for Safe Actions and Audit Records."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.actions.models import (
    ActionAuditRecord,
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    SafeAction,
    TargetType,
)

logger = logging.getLogger("sentinelops.actions.store")


class ActionNotFoundError(Exception):
    """Raised when an action_id does not exist."""

    def __init__(self, action_id: str) -> None:
        super().__init__(f"Safe action '{action_id}' not found.")
        self.action_id = action_id


class DuplicateActiveActionError(Exception):
    """Raised when an active action already exists for the target."""

    def __init__(self, target_type: str, target_id: str) -> None:
        super().__init__(
            f"An active action is already in flight for target '{target_type}:{target_id}'."
        )
        self.target_type = target_type
        self.target_id = target_id


class InvalidActionStateTransitionError(Exception):
    """Raised when an invalid state transition is requested."""

    def __init__(self, action_id: str, message: str) -> None:
        super().__init__(f"Invalid transition for action '{action_id}': {message}")
        self.action_id = action_id


class SqliteActionStore:
    """Manages durable SQLite persistence and atomic state transitions for Safe Actions."""

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

    def close(self) -> None:
        """Closes the underlying SQLite database connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def _init_db(self) -> None:
        """Initializes tables, constraints, and indexes."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            if self._db_path != ":memory:":
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")

            # Ensure projects table exists
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

            # 1. safe_actions table with foreign key ON DELETE RESTRICT
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS safe_actions (
                    action_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    incident_id TEXT,
                    action_type TEXT NOT NULL CHECK (action_type IN ('test_connector', 'retry_notification')),
                    target_type TEXT NOT NULL CHECK (target_type IN ('connector', 'notification')),
                    target_id TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    requested_by_claim TEXT NOT NULL,
                    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
                    policy_status TEXT NOT NULL CHECK (policy_status IN ('allowed', 'denied')),
                    policy_denial_reason TEXT,
                    approval_status TEXT NOT NULL CHECK (approval_status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')),
                    execution_status TEXT NOT NULL CHECK (execution_status IN ('not_started', 'pending', 'executing', 'succeeded', 'failed', 'timed_out', 'aborted')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_by_claim TEXT,
                    approved_at TEXT,
                    approved_fingerprint TEXT,
                    rejection_reason TEXT,
                    executed_at TEXT,
                    completed_at TEXT,
                    execution_result_json TEXT,
                    failure_reason TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE RESTRICT
                );
                """
            )

            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_safe_actions_project_id ON safe_actions(project_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_safe_actions_incident_id ON safe_actions(incident_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_safe_actions_status ON safe_actions(approval_status, execution_status);")

            # Scoped unique active target index:
            # Prevents duplicate active actions on same target, but permits new proposals
            # if prior ones were denied, rejected, cancelled, or aborted.
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_safe_actions_unique_active_target
                ON safe_actions(target_type, target_id)
                WHERE policy_status = 'allowed'
                  AND execution_status IN ('not_started', 'pending', 'executing')
                  AND approval_status NOT IN ('rejected', 'cancelled', 'expired');
                """
            )

            # 2. action_audit_records table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS action_audit_records (
                    audit_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_claim TEXT NOT NULL,
                    previous_state_json TEXT NOT NULL,
                    new_state_json TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (action_id) REFERENCES safe_actions(action_id) ON DELETE RESTRICT
                );
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_action_audit_action_id ON action_audit_records(action_id);")
            self._conn.commit()

    def create_action(
        self, action: SafeAction, audit_records: List[ActionAuditRecord]
    ) -> SafeAction:
        """Atomically inserts a new safe action and its initial audit records."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO safe_actions (
                        action_id, project_id, incident_id, action_type, target_type, target_id,
                        parameters_json, fingerprint, requested_by_claim, risk_level, policy_status,
                        policy_denial_reason, approval_status, execution_status, created_at, updated_at,
                        approved_by_claim, approved_at, approved_fingerprint, rejection_reason,
                        executed_at, completed_at, execution_result_json, failure_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        action.action_id,
                        action.project_id,
                        action.incident_id,
                        action.action_type.value,
                        action.target_type.value,
                        action.target_id,
                        json.dumps(action.parameters),
                        action.fingerprint,
                        action.requested_by_claim,
                        action.risk_level.value,
                        action.policy_status.value,
                        action.policy_denial_reason,
                        action.approval_status.value,
                        action.execution_status.value,
                        action.created_at.isoformat(),
                        action.updated_at.isoformat(),
                        action.approved_by_claim,
                        action.approved_at.isoformat() if action.approved_at else None,
                        action.approved_fingerprint,
                        action.rejection_reason,
                        action.executed_at.isoformat() if action.executed_at else None,
                        action.completed_at.isoformat() if action.completed_at else None,
                        json.dumps(action.execution_result) if action.execution_result else None,
                        action.failure_reason,
                    ),
                )
                for audit in audit_records:
                    self._insert_audit_record(cursor, audit)
                self._conn.commit()
                return action
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                err_str = str(exc).lower()
                if "target_type" in err_str or "idx_safe_actions_unique_active_target" in err_str:
                    raise DuplicateActiveActionError(action.target_type.value, action.target_id)
                raise
            except Exception:
                self._conn.rollback()
                raise

    def get_action(self, action_id: str) -> Optional[SafeAction]:
        """Retrieves a single safe action by ID."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_action(row)

    def list_actions(
        self,
        project_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        approval_status: Optional[ApprovalStatus] = None,
        execution_status: Optional[ExecutionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SafeAction]:
        """Lists actions matching filters, ordered chronologically newest first."""
        query = "SELECT * FROM safe_actions WHERE 1=1"
        params: List[Any] = []

        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if incident_id:
            query += " AND incident_id = ?"
            params.append(incident_id)
        if approval_status:
            query += " AND approval_status = ?"
            params.append(approval_status.value)
        if execution_status:
            query += " AND execution_status = ?"
            params.append(execution_status.value)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_action(r) for r in rows]

    def has_active_action_for_target(self, target_type: TargetType, target_id: str) -> bool:
        """Checks if an active, non-terminal allowed action already exists for the target."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM safe_actions
                WHERE target_type = ?
                  AND target_id = ?
                  AND policy_status = 'allowed'
                  AND execution_status IN ('not_started', 'pending', 'executing')
                  AND approval_status NOT IN ('rejected', 'cancelled', 'expired')
                LIMIT 1;
                """,
                (target_type.value, target_id),
            )
            return cursor.fetchone() is not None

    def approve_action(
        self,
        action_id: str,
        operator_claim: str,
        comment: Optional[str],
        now: datetime,
    ) -> Tuple[SafeAction, bool]:
        """Atomically approves an action and appends an APPROVED audit record.

        Returns (action, was_idempotent).
        """
        now_str = now.isoformat()
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                row = cursor.fetchone()
                if not row:
                    raise ActionNotFoundError(action_id)

                action = self._row_to_action(row)

                # Idempotency check
                if (
                    action.approval_status == ApprovalStatus.APPROVED
                    and action.approved_by_claim == operator_claim
                    and action.approved_fingerprint == action.fingerprint
                ):
                    return action, True

                if action.approval_status != ApprovalStatus.PENDING:
                    raise InvalidActionStateTransitionError(
                        action_id,
                        f"Cannot approve action with approval_status '{action.approval_status.value}'.",
                    )

                if action.policy_status != PolicyStatus.ALLOWED:
                    raise InvalidActionStateTransitionError(
                        action_id,
                        f"Cannot approve action with policy_status '{action.policy_status.value}'.",
                    )

                prev_state = {
                    "approval_status": action.approval_status.value,
                    "execution_status": action.execution_status.value,
                }
                new_state = {
                    "approval_status": ApprovalStatus.APPROVED.value,
                    "execution_status": action.execution_status.value,
                    "approved_by_claim": operator_claim,
                    "approved_fingerprint": action.fingerprint,
                }

                cursor.execute(
                    """
                    UPDATE safe_actions SET
                        approval_status = 'approved',
                        approved_by_claim = ?,
                        approved_at = ?,
                        approved_fingerprint = ?,
                        updated_at = ?
                    WHERE action_id = ?;
                    """,
                    (operator_claim, now_str, action.fingerprint, now_str, action_id),
                )

                audit = ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type="APPROVED",
                    actor_claim=operator_claim,
                    previous_state=prev_state,
                    new_state=new_state,
                    message=f"Action approved by {operator_claim}" + (f": {comment}" if comment else "."),
                    payload={"comment": comment, "fingerprint": action.fingerprint},
                    created_at=now,
                )
                self._insert_audit_record(cursor, audit)
                self._conn.commit()

                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                updated_action = self._row_to_action(cursor.fetchone())
                return updated_action, False
            except Exception:
                self._conn.rollback()
                raise

    def reject_action(
        self,
        action_id: str,
        operator_claim: str,
        reason: str,
        now: datetime,
    ) -> Tuple[SafeAction, bool]:
        """Atomically rejects an action and marks execution_status as aborted.

        Returns (action, was_idempotent).
        """
        now_str = now.isoformat()
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                row = cursor.fetchone()
                if not row:
                    raise ActionNotFoundError(action_id)

                action = self._row_to_action(row)

                # Idempotency check
                if action.approval_status == ApprovalStatus.REJECTED:
                    return action, True

                if action.approval_status != ApprovalStatus.PENDING:
                    raise InvalidActionStateTransitionError(
                        action_id,
                        f"Cannot reject action with approval_status '{action.approval_status.value}'.",
                    )

                prev_state = {
                    "approval_status": action.approval_status.value,
                    "execution_status": action.execution_status.value,
                }
                new_state = {
                    "approval_status": ApprovalStatus.REJECTED.value,
                    "execution_status": ExecutionStatus.ABORTED.value,
                    "rejection_reason": reason,
                }

                cursor.execute(
                    """
                    UPDATE safe_actions SET
                        approval_status = 'rejected',
                        execution_status = 'aborted',
                        rejection_reason = ?,
                        failure_reason = ?,
                        updated_at = ?
                    WHERE action_id = ?;
                    """,
                    (reason, f"Rejected: {reason}", now_str, action_id),
                )

                audit = ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type="REJECTED",
                    actor_claim=operator_claim,
                    previous_state=prev_state,
                    new_state=new_state,
                    message=f"Action rejected by {operator_claim}: {reason}",
                    payload={"reason": reason},
                    created_at=now,
                )
                self._insert_audit_record(cursor, audit)
                self._conn.commit()

                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                updated_action = self._row_to_action(cursor.fetchone())
                return updated_action, False
            except Exception:
                self._conn.rollback()
                raise

    def claim_action_for_execution(
        self,
        action_id: str,
        expected_fingerprint: str,
        now: datetime,
    ) -> Tuple[bool, Optional[SafeAction], Optional[str]]:
        """Atomically validates DB prerequisites and claims execution in a single write transaction.

        Returns:
            (True, claimed_action, None) on success.
            (False, None, error_or_abort_reason) on failure or disqualification.
        """
        now_str = now.isoformat()
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("BEGIN IMMEDIATE;")
            try:
                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                row = cursor.fetchone()
                if not row:
                    cursor.execute("ROLLBACK;")
                    return False, None, f"Action '{action_id}' not found."

                action = self._row_to_action(row)

                if action.approval_status != ApprovalStatus.APPROVED or action.execution_status != ExecutionStatus.NOT_STARTED:
                    cursor.execute("ROLLBACK;")
                    return (
                        False,
                        None,
                        f"Action '{action_id}' is not in approved/not_started state (current: {action.approval_status.value}/{action.execution_status.value}).",
                    )

                # Fingerprint verification
                if action.fingerprint != expected_fingerprint or action.approved_fingerprint != expected_fingerprint:
                    abort_reason = "Fingerprint mismatch at execution claim."
                    self._record_abort_in_tx(cursor, action, abort_reason, now_str, now)
                    cursor.execute("COMMIT;")
                    return False, None, abort_reason

                # Database-backed target existence and project association check on the same connection
                target_type = action.target_type
                target_id = action.target_id
                project_id = action.project_id

                if target_type == TargetType.CONNECTOR:
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='connectors';")
                    if cursor.fetchone():
                        cursor.execute("SELECT project_id FROM connectors WHERE connector_id = ?;", (target_id,))
                        conn_row = cursor.fetchone()
                        if not conn_row or conn_row["project_id"] != project_id:
                            abort_reason = f"Connector target '{target_id}' no longer exists or project drifted."
                            self._record_abort_in_tx(cursor, action, abort_reason, now_str, now)
                            cursor.execute("COMMIT;")
                            return False, None, abort_reason

                elif target_type == TargetType.NOTIFICATION:
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notifications';")
                    if cursor.fetchone():
                        cursor.execute("SELECT project_id FROM notifications WHERE notification_id = ?;", (target_id,))
                        notif_row = cursor.fetchone()
                        if not notif_row or notif_row["project_id"] != project_id:
                            abort_reason = f"Notification target '{target_id}' no longer exists or project drifted."
                            self._record_abort_in_tx(cursor, action, abort_reason, now_str, now)
                            cursor.execute("COMMIT;")
                            return False, None, abort_reason

                # Atomic transition to EXECUTING
                prev_state = {
                    "approval_status": action.approval_status.value,
                    "execution_status": action.execution_status.value,
                }
                new_state = {
                    "approval_status": action.approval_status.value,
                    "execution_status": ExecutionStatus.EXECUTING.value,
                }

                cursor.execute(
                    """
                    UPDATE safe_actions SET
                        execution_status = 'executing',
                        executed_at = ?,
                        updated_at = ?
                    WHERE action_id = ?;
                    """,
                    (now_str, now_str, action_id),
                )

                audit = ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type="EXECUTION_STARTED",
                    actor_claim=action.approved_by_claim or "system",
                    previous_state=prev_state,
                    new_state=new_state,
                    message="Authoritative execution lock claimed; executing safe action.",
                    payload={"fingerprint": expected_fingerprint},
                    created_at=now,
                )
                self._insert_audit_record(cursor, audit)
                cursor.execute("COMMIT;")

                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                claimed_action = self._row_to_action(cursor.fetchone())
                return True, claimed_action, None

            except Exception as exc:
                cursor.execute("ROLLBACK;")
                logger.error("Error in claim_action_for_execution: %s", exc)
                raise

    def complete_execution(
        self,
        action_id: str,
        final_status: ExecutionStatus,
        result: Optional[Dict[str, Any]],
        failure_reason: Optional[str],
        event_type: str,
        actor_claim: str,
        message: str,
        now: datetime,
    ) -> SafeAction:
        """Atomically updates action to terminal execution status and records the result audit."""
        now_str = now.isoformat()
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                row = cursor.fetchone()
                if not row:
                    raise ActionNotFoundError(action_id)

                action = self._row_to_action(row)
                prev_state = {
                    "execution_status": action.execution_status.value,
                }
                new_state = {
                    "execution_status": final_status.value,
                    "failure_reason": failure_reason,
                }

                cursor.execute(
                    """
                    UPDATE safe_actions SET
                        execution_status = ?,
                        completed_at = ?,
                        execution_result_json = ?,
                        failure_reason = ?,
                        updated_at = ?
                    WHERE action_id = ?;
                    """,
                    (
                        final_status.value,
                        now_str,
                        json.dumps(result) if result else None,
                        failure_reason,
                        now_str,
                        action_id,
                    ),
                )

                audit = ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type=event_type,
                    actor_claim=actor_claim,
                    previous_state=prev_state,
                    new_state=new_state,
                    message=message,
                    payload={"result": result, "failure_reason": failure_reason},
                    created_at=now,
                )
                self._insert_audit_record(cursor, audit)
                self._conn.commit()

                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                return self._row_to_action(cursor.fetchone())
            except Exception:
                self._conn.rollback()
                raise

    def abort_action(
        self,
        action_id: str,
        reason: str,
        event_type: str,
        actor_claim: str,
        now: datetime,
    ) -> SafeAction:
        """Atomically transitions an action to ABORTED and DENIED with an audit record."""
        now_str = now.isoformat()
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                row = cursor.fetchone()
                if not row:
                    raise ActionNotFoundError(action_id)

                action = self._row_to_action(row)
                prev_state = {
                    "policy_status": action.policy_status.value,
                    "execution_status": action.execution_status.value,
                }
                new_state = {
                    "policy_status": PolicyStatus.DENIED.value,
                    "execution_status": ExecutionStatus.ABORTED.value,
                    "failure_reason": reason,
                }

                cursor.execute(
                    """
                    UPDATE safe_actions SET
                        policy_status = 'denied',
                        execution_status = 'aborted',
                        failure_reason = ?,
                        updated_at = ?
                    WHERE action_id = ?;
                    """,
                    (reason, now_str, action_id),
                )

                audit = ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type=event_type,
                    actor_claim=actor_claim,
                    previous_state=prev_state,
                    new_state=new_state,
                    message=f"Action aborted: {reason}",
                    payload={"reason": reason},
                    created_at=now,
                )
                self._insert_audit_record(cursor, audit)
                self._conn.commit()

                cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                return self._row_to_action(cursor.fetchone())
            except Exception:
                self._conn.rollback()
                raise

    def reconcile_interrupted_executions_on_startup(
        self, now: Optional[datetime] = None
    ) -> List[SafeAction]:
        """Atomically reconciles any actions stranded in 'executing' across a process restart.

        Transitions each orphaned action to:
            approval_status = approved (preserved)
            execution_status = aborted
            completed_at = now
            failure_reason = "Execution interrupted across backend restart."

        Appends an explicit terminal audit record 'EXECUTION_ABORTED_ON_RESTART' per action.
        This releases the unique active-target constraint and prevents duplicate retries.
        """
        reconcile_time = now or datetime.now(timezone.utc)
        now_str = reconcile_time.isoformat()
        reconciled: List[SafeAction] = []

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM safe_actions WHERE execution_status = 'executing';")
            rows = cursor.fetchall()
            if not rows:
                return []

            for row in rows:
                action = self._row_to_action(row)
                action_id = action.action_id
                try:
                    cursor.execute(
                        """
                        UPDATE safe_actions SET
                            execution_status = 'aborted',
                            completed_at = ?,
                            failure_reason = 'Execution interrupted across backend restart.',
                            updated_at = ?
                        WHERE action_id = ? AND execution_status = 'executing';
                        """,
                        (now_str, now_str, action_id),
                    )
                    if cursor.rowcount > 0:
                        prev_state = {
                            "approval_status": action.approval_status.value,
                            "execution_status": "executing",
                        }
                        new_state = {
                            "approval_status": action.approval_status.value,
                            "execution_status": "aborted",
                            "failure_reason": "Execution interrupted across backend restart.",
                        }
                        audit = ActionAuditRecord(
                            audit_id=str(uuid.uuid4()),
                            action_id=action_id,
                            event_type="EXECUTION_ABORTED_ON_RESTART",
                            actor_claim="system",
                            previous_state=prev_state,
                            new_state=new_state,
                            message="SentinelOps detected orphaned execution claim during startup; execution aborted without automatic retry.",
                            payload={
                                "interrupted_execution_status": "executing",
                                "original_executed_at": action.executed_at.isoformat() if action.executed_at else None,
                                "reason": "Execution interrupted across backend restart.",
                            },
                            created_at=reconcile_time,
                        )
                        self._insert_audit_record(cursor, audit)
                        self._conn.commit()

                        cursor.execute("SELECT * FROM safe_actions WHERE action_id = ?;", (action_id,))
                        updated_row = cursor.fetchone()
                        if updated_row:
                            reconciled.append(self._row_to_action(updated_row))
                    else:
                        self._conn.rollback()
                except Exception as exc:
                    self._conn.rollback()
                    logger.error("Failed to reconcile orphaned action %s on startup: %s", action_id, exc)

        return reconciled

    def list_audit_records(self, action_id: str) -> List[ActionAuditRecord]:
        """Lists all append-only audit records for an action, ordered chronologically oldest first."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT * FROM action_audit_records
                WHERE action_id = ?
                ORDER BY created_at ASC;
                """,
                (action_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_audit(r) for r in rows]

    def _record_abort_in_tx(
        self,
        cursor: sqlite3.Cursor,
        action: SafeAction,
        reason: str,
        now_str: str,
        now: datetime,
    ) -> None:
        """Helper to mark an action aborted and record POLICY_REVALIDATION_FAILED inside an existing tx."""
        cursor.execute(
            """
            UPDATE safe_actions SET
                policy_status = 'denied',
                execution_status = 'aborted',
                failure_reason = ?,
                updated_at = ?
            WHERE action_id = ?;
            """,
            (reason, now_str, action.action_id),
        )
        audit = ActionAuditRecord(
            audit_id=str(uuid.uuid4()),
            action_id=action.action_id,
            event_type="POLICY_REVALIDATION_FAILED",
            actor_claim=action.approved_by_claim or "system",
            previous_state={"execution_status": action.execution_status.value},
            new_state={"execution_status": ExecutionStatus.ABORTED.value, "failure_reason": reason},
            message=f"Execution aborted during re-validation: {reason}",
            payload={"reason": reason},
            created_at=now,
        )
        self._insert_audit_record(cursor, audit)

    def _insert_audit_record(self, cursor: sqlite3.Cursor, audit: ActionAuditRecord) -> None:
        cursor.execute(
            """
            INSERT INTO action_audit_records (
                audit_id, action_id, event_type, actor_claim, previous_state_json,
                new_state_json, message, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                audit.audit_id,
                audit.action_id,
                audit.event_type,
                audit.actor_claim,
                json.dumps(audit.previous_state),
                json.dumps(audit.new_state),
                audit.message,
                json.dumps(audit.payload) if audit.payload else None,
                audit.created_at.isoformat(),
            ),
        )

    def _row_to_action(self, row: sqlite3.Row) -> SafeAction:
        return SafeAction(
            action_id=row["action_id"],
            project_id=row["project_id"],
            incident_id=row["incident_id"],
            action_type=ActionType(row["action_type"]),
            target_type=TargetType(row["target_type"]),
            target_id=row["target_id"],
            parameters=json.loads(row["parameters_json"]) if row["parameters_json"] else {},
            fingerprint=row["fingerprint"],
            requested_by_claim=row["requested_by_claim"],
            risk_level=RiskLevel(row["risk_level"]),
            policy_status=PolicyStatus(row["policy_status"]),
            policy_denial_reason=row["policy_denial_reason"],
            approval_status=ApprovalStatus(row["approval_status"]),
            execution_status=ExecutionStatus(row["execution_status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            approved_by_claim=row["approved_by_claim"],
            approved_at=datetime.fromisoformat(row["approved_at"]) if row["approved_at"] else None,
            approved_fingerprint=row["approved_fingerprint"],
            rejection_reason=row["rejection_reason"],
            executed_at=datetime.fromisoformat(row["executed_at"]) if row["executed_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            execution_result=json.loads(row["execution_result_json"]) if row["execution_result_json"] else None,
            failure_reason=row["failure_reason"],
        )

    def _row_to_audit(self, row: sqlite3.Row) -> ActionAuditRecord:
        return ActionAuditRecord(
            audit_id=row["audit_id"],
            action_id=row["action_id"],
            event_type=row["event_type"],
            actor_claim=row["actor_claim"],
            previous_state=json.loads(row["previous_state_json"]),
            new_state=json.loads(row["new_state_json"]),
            message=row["message"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )
