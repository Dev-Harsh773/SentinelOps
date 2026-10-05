"""Unit tests for SqliteActionStore persistence, transactional locks, constraints, and audit trails."""

from datetime import datetime, timezone
import pytest
import sqlite3

from app.actions.models import (
    ActionAuditRecord,
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    SafeAction,
    TargetType,
    compute_action_fingerprint,
)
from app.actions.store import (
    ActionNotFoundError,
    DuplicateActiveActionError,
    InvalidActionStateTransitionError,
    SqliteActionStore,
)


@pytest.fixture
def store():
    """Provides an isolated in-memory SqliteActionStore instance."""
    s = SqliteActionStore(db_path=":memory:")
    # Seed projects table for foreign key satisfaction
    with s._lock:
        cursor = s._conn.cursor()
        cursor.execute(
            """
            INSERT INTO projects (
                project_id, name, workspace_path, normalized_path, is_git, status, created_at, updated_at
            ) VALUES ('test-proj', 'Test Project', '/work', '/work', 1, 'ready', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
            """
        )
        # Seed connectors table
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
                updated_at TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            INSERT INTO connectors VALUES ('conn-1', 'test-proj', 'Main Poller', 'http_poller', '{}', 'active', '2026-01-01', '2026-01-01');
            """
        )
        # Seed notifications table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                delivery_status TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            INSERT INTO notifications VALUES ('notif-1', 'test-proj', 'failed');
            """
        )
        s._conn.commit()
    yield s
    s.close()


def _make_action(action_id="act-1", target_id="conn-1", target_type=TargetType.CONNECTOR, action_type=ActionType.TEST_CONNECTOR):
    now = datetime.now(timezone.utc)
    fp = compute_action_fingerprint(
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        project_id="test-proj",
        incident_id=None,
        risk_level=RiskLevel.LOW,
        parameters={},
    )
    return SafeAction(
        action_id=action_id,
        project_id="test-proj",
        incident_id=None,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        parameters={},
        fingerprint=fp,
        requested_by_claim="operator:admin",
        risk_level=RiskLevel.LOW,
        policy_status=PolicyStatus.ALLOWED,
        policy_denial_reason=None,
        approval_status=ApprovalStatus.PENDING,
        execution_status=ExecutionStatus.NOT_STARTED,
        created_at=now,
        updated_at=now,
    )


def test_insert_and_get_action(store):
    """Test inserting an action with audit record and retrieving it."""
    action = _make_action()
    audit = ActionAuditRecord(
        audit_id="aud-1",
        action_id=action.action_id,
        event_type="PROPOSED",
        actor_claim="operator:admin",
        previous_state={},
        new_state={"approval_status": "pending"},
        message="Proposed test action",
    )
    store.create_action(action, [audit])

    retrieved = store.get_action(action.action_id)
    assert retrieved is not None
    assert retrieved.action_id == action.action_id
    assert retrieved.fingerprint == action.fingerprint
    assert retrieved.approval_status == ApprovalStatus.PENDING

    audits = store.list_audit_records(action.action_id)
    assert len(audits) == 1
    assert audits[0].event_type == "PROPOSED"


def test_scoped_unique_active_target_index(store):
    """Test that duplicate active actions on same target are rejected, but allowed once non-active."""
    act1 = _make_action(action_id="act-1", target_id="conn-1")
    store.create_action(act1, [])

    # Second active proposal on same target raises DuplicateActiveActionError
    act2 = _make_action(action_id="act-2", target_id="conn-1")
    with pytest.raises(DuplicateActiveActionError):
        store.create_action(act2, [])

    # Now reject act1 (it becomes non-active: rejected / aborted)
    store.reject_action(act1.action_id, "operator:admin", "Cancelled", datetime.now(timezone.utc))

    # Now act2 can be created successfully!
    act2_new = _make_action(action_id="act-2", target_id="conn-1")
    created = store.create_action(act2_new, [])
    assert created.action_id == "act-2"


def test_atomic_approval_and_idempotency(store):
    """Test atomic approval and idempotent repeated approvals."""
    action = _make_action()
    store.create_action(action, [])

    now = datetime.now(timezone.utc)
    approved, was_idempotent = store.approve_action(action.action_id, "operator:admin", "LGTM", now)
    assert not was_idempotent
    assert approved.approval_status == ApprovalStatus.APPROVED
    assert approved.approved_by_claim == "operator:admin"
    assert approved.approved_fingerprint == action.fingerprint

    # Audit record created
    audits = store.list_audit_records(action.action_id)
    assert len(audits) == 1
    assert audits[0].event_type == "APPROVED"

    # Second call is idempotent
    approved2, was_idempotent2 = store.approve_action(action.action_id, "operator:admin", "LGTM", now)
    assert was_idempotent2
    assert approved2.approval_status == ApprovalStatus.APPROVED
    # No duplicate audit record inserted on idempotent call
    assert len(store.list_audit_records(action.action_id)) == 1


def test_atomic_rejection_and_idempotency(store):
    """Test atomic rejection transitions to REJECTED and ABORTED."""
    action = _make_action()
    store.create_action(action, [])

    now = datetime.now(timezone.utc)
    rejected, was_idempotent = store.reject_action(action.action_id, "operator:admin", "Too risky", now)
    assert not was_idempotent
    assert rejected.approval_status == ApprovalStatus.REJECTED
    assert rejected.execution_status == ExecutionStatus.ABORTED

    # Idempotent rejection
    rejected2, was_idempotent2 = store.reject_action(action.action_id, "operator:admin", "Too risky", now)
    assert was_idempotent2


def test_claim_action_for_execution_atomic_locks(store):
    """Test that claim_action_for_execution transitions APPROVED to EXECUTING atomically."""
    action = _make_action()
    store.create_action(action, [])

    now = datetime.now(timezone.utc)
    # Cannot claim unapproved action
    claimed, act, err = store.claim_action_for_execution(action.action_id, action.fingerprint, now)
    assert not claimed
    assert "not in approved" in err

    # Approve action
    store.approve_action(action.action_id, "operator:admin", "Approved", now)

    # Claim action
    claimed, act, err = store.claim_action_for_execution(action.action_id, action.fingerprint, now)
    assert claimed
    assert act.execution_status == ExecutionStatus.EXECUTING

    # Attempting to claim again fails (already EXECUTING)
    claimed2, act2, err2 = store.claim_action_for_execution(action.action_id, action.fingerprint, now)
    assert not claimed2


def test_claim_action_fingerprint_mismatch_aborts(store):
    """Test that a fingerprint mismatch during execution claim marks the action ABORTED."""
    action = _make_action()
    store.create_action(action, [])
    now = datetime.now(timezone.utc)
    store.approve_action(action.action_id, "operator:admin", "Approved", now)

    # Claim with wrong fingerprint
    claimed, act, err = store.claim_action_for_execution(action.action_id, "wrong-hash", now)
    assert not claimed
    assert "Fingerprint mismatch" in err

    updated = store.get_action(action.action_id)
    assert updated.execution_status == ExecutionStatus.ABORTED
    assert updated.policy_status == PolicyStatus.DENIED


def test_audit_immutability_on_delete_restrict(store):
    """Test that action audit records are append-only and deletion is restricted."""
    action = _make_action()
    store.create_action(action, [])

    # Foreign key ON DELETE RESTRICT prevents deleting safe_actions when audits exist
    with store._lock:
        cursor = store._conn.cursor()
        cursor.execute(
            """
            INSERT INTO action_audit_records VALUES (
                'aud-imm', ?, 'PROPOSED', 'admin', '{}', '{}', 'Test audit', NULL, '2026-01-01'
            );
            """,
            (action.action_id,),
        )
        store._conn.commit()

        # Attempting to delete action directly violates foreign key constraint
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute("DELETE FROM safe_actions WHERE action_id = ?;", (action.action_id,))
            store._conn.commit()


def test_reconcile_interrupted_executions_on_startup(store):
    """Test deterministic startup reconciliation of orphaned EXECUTING actions:

    - executing action exists before startup
    - startup changes it to ABORTED
    - approval remains APPROVED (human approval preserved)
    - completed_at populated
    - failure_reason populated ("Execution interrupted across backend restart.")
    - original executed_at, approved_by_claim, approved_fingerprint preserved
    - EXECUTION_ABORTED_ON_RESTART appended exactly once
    - second run is idempotent (returns empty, no duplicate audits)
    - terminal actions (succeeded, failed, aborted) are untouched
    - NOT_STARTED approved actions are untouched
    - active-target constraint is released afterward (fresh action on same target succeeds)
    """
    now = datetime.now(timezone.utc)

    # Seed connector targets in connectors table so claim_action_for_execution verifies target existence
    with store._lock:
        cursor = store._conn.cursor()
        for tid in ["target-a", "target-b", "target-c", "target-d", "target-e"]:
            cursor.execute(
                "INSERT OR IGNORE INTO connectors VALUES (?, 'test-proj', 'Name', 'http_poller', '{}', 'active', '2026-01-01', '2026-01-01');",
                (tid,),
            )
        store._conn.commit()

    # 1. Action A: Orphaned in EXECUTING
    act_a = _make_action(action_id="act-a", target_id="target-a")
    store.create_action(act_a, [])
    store.approve_action("act-a", "operator:lead", "Approved A", now)
    claimed, act_claimed, _ = store.claim_action_for_execution("act-a", act_a.fingerprint, now)
    assert claimed
    assert act_claimed.execution_status == ExecutionStatus.EXECUTING
    original_executed_at = act_claimed.executed_at

    # 2. Action B: NOT_STARTED approved action (must remain NOT_STARTED)
    act_b = _make_action(action_id="act-b", target_id="target-b")
    store.create_action(act_b, [])
    store.approve_action("act-b", "operator:lead", "Approved B", now)

    # 3. Action C: SUCCEEDED action (must remain SUCCEEDED)
    act_c = _make_action(action_id="act-c", target_id="target-c")
    store.create_action(act_c, [])
    store.approve_action("act-c", "operator:lead", "Approved C", now)
    store.claim_action_for_execution("act-c", act_c.fingerprint, now)
    store.complete_execution(
        action_id="act-c",
        final_status=ExecutionStatus.SUCCEEDED,
        result={"status": "ok"},
        failure_reason=None,
        event_type="EXECUTION_COMPLETED",
        actor_claim="operator:lead",
        message="Completed successfully",
        now=now,
    )

    # 4. Action D: FAILED action (must remain FAILED)
    act_d = _make_action(action_id="act-d", target_id="target-d")
    store.create_action(act_d, [])
    store.approve_action("act-d", "operator:lead", "Approved D", now)
    store.claim_action_for_execution("act-d", act_d.fingerprint, now)
    store.complete_execution(
        action_id="act-d",
        final_status=ExecutionStatus.FAILED,
        result=None,
        failure_reason="Network error",
        event_type="EXECUTION_FAILED",
        actor_claim="operator:lead",
        message="Failed",
        now=now,
    )

    # 5. Action E: REJECTED / ABORTED action (must remain ABORTED)
    act_e = _make_action(action_id="act-e", target_id="target-e")
    store.create_action(act_e, [])
    store.reject_action("act-e", "operator:lead", "Rejected E", now)

    # Run startup reconciliation
    reconciled = store.reconcile_interrupted_executions_on_startup()
    assert len(reconciled) == 1
    assert reconciled[0].action_id == "act-a"

    # Verify Action A state
    updated_a = store.get_action("act-a")
    assert updated_a.approval_status == ApprovalStatus.APPROVED
    assert updated_a.execution_status == ExecutionStatus.ABORTED
    assert updated_a.completed_at is not None
    assert updated_a.failure_reason == "Execution interrupted across backend restart."
    assert updated_a.executed_at == original_executed_at
    assert updated_a.approved_by_claim == "operator:lead"
    assert updated_a.approved_fingerprint == act_a.fingerprint
    assert updated_a.fingerprint == act_a.fingerprint

    # Verify Action A audit record
    audits_a = store.list_audit_records("act-a")
    event_types_a = [au.event_type for au in audits_a]
    assert "EXECUTION_ABORTED_ON_RESTART" in event_types_a
    assert event_types_a.count("EXECUTION_ABORTED_ON_RESTART") == 1
    abort_audit = [au for au in audits_a if au.event_type == "EXECUTION_ABORTED_ON_RESTART"][0]
    assert "without automatic retry" in abort_audit.message
    assert abort_audit.actor_claim == "system"

    # Verify other actions are completely untouched
    updated_b = store.get_action("act-b")
    assert updated_b.execution_status == ExecutionStatus.NOT_STARTED
    assert updated_b.approval_status == ApprovalStatus.APPROVED

    updated_c = store.get_action("act-c")
    assert updated_c.execution_status == ExecutionStatus.SUCCEEDED

    updated_d = store.get_action("act-d")
    assert updated_d.execution_status == ExecutionStatus.FAILED

    updated_e = store.get_action("act-e")
    assert updated_e.execution_status == ExecutionStatus.ABORTED
    assert updated_e.approval_status == ApprovalStatus.REJECTED

    # Verify idempotency on second run
    reconciled_2 = store.reconcile_interrupted_executions_on_startup()
    assert len(reconciled_2) == 0
    audits_a_after = store.list_audit_records("act-a")
    assert len(audits_a_after) == len(audits_a)

    # Verify active-target constraint is released: fresh action for target-a can be created
    fresh_act_a = _make_action(action_id="act-a-new", target_id="target-a")
    store.create_action(fresh_act_a, [])
    assert store.get_action("act-a-new") is not None

