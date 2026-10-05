"""Integration and concurrency tests for ActionService."""

import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.actions.executors.connector_test import ConnectorTestExecutor
from app.actions.executors.notification_retry import NotificationRetryExecutor
from app.actions.executors.registry import ActionExecutorRegistry
from app.actions.models import (
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    TargetType,
)
from app.actions.policy import ActionPolicyEngine
from app.actions.service import ActionExecutionError, ActionService
from app.actions.store import DuplicateActiveActionError, SqliteActionStore
from app.connectors.models import Connector, ConnectorConfig, ConnectorStatus, ConnectorType
from app.connectors.service import ConnectorService
from app.connectors.store import SqliteConnectorStore
from app.incidents.models import Incident, IncidentStatus, Severity
from app.incidents.repository import InMemoryIncidentRepository
from app.incidents.service import IncidentService
from app.notifications.models import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationResponse,
    NotificationType,
    ReadStatus,
)
from app.notifications.service import NotificationService
from app.notifications.store import SqliteNotificationStore


@pytest.fixture
def service_env(tmp_path):
    """Sets up an isolated service environment with shared sqlite metadata db."""
    db_file = str(tmp_path / "service_test.db")
    action_store = SqliteActionStore(db_path=db_file)
    connector_store = SqliteConnectorStore(db_path=db_file)
    notification_store = SqliteNotificationStore(db_path=db_file)
    incident_repo = InMemoryIncidentRepository()
    incident_service = IncidentService(repository=incident_repo)

    now = datetime.now(timezone.utc)
    with action_store._lock:
        cursor = action_store._conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO projects (
                project_id, name, workspace_path, normalized_path, is_git, status, created_at, updated_at
            ) VALUES ('proj-1', 'Project 1', '/w', '/w', 1, 'ready', '2026-01-01', '2026-01-01');
            """
        )
        action_store._conn.commit()

    # Seed connector
    conn = Connector(
        connector_id="conn-1",
        project_id="proj-1",
        name="Poller",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(url="http://127.0.0.1:8000/health"),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(conn)

    # Seed notification
    notif = Notification(
        notification_id="notif-1",
        project_id="proj-1",
        incident_id=None,
        subscription_id=None,
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Title",
        message="Msg",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="http://recip",
        delivery_status=DeliveryStatus.FAILED,
        read_status=ReadStatus.UNREAD,
        attempt_count=3,
        created_at=now,
        updated_at=now,
    )
    notification_store.create_notification(notif)

    # Seed incident
    inc = Incident(
        id="inc-1",
        title="Alert",
        summary="Sum",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="svc",
        environment="prod",
        created_at=now,
        updated_at=now,
        project_id="proj-1",
    )
    incident_repo.create(inc)

    # Mock services for executors
    mock_conn_service = MagicMock(spec=ConnectorService)
    mock_conn_service.test_connector = AsyncMock(return_value={"status": "success", "status_code": 200, "latency_ms": 10.0})

    mock_notif_service = MagicMock(spec=NotificationService)
    mock_notif_resp = MagicMock(spec=NotificationResponse)
    mock_notif_resp.notification_id = "notif-1"
    mock_notif_resp.delivery_status = DeliveryStatus.PENDING
    mock_notif_resp.attempt_count = 0
    mock_notif_service.atomic_retry_notification.return_value = (True, mock_notif_resp, None)

    policy_engine = ActionPolicyEngine(
        action_store=action_store,
        connector_store=connector_store,
        notification_store=notification_store,
        incident_service=incident_service,
    )

    registry = ActionExecutorRegistry()
    registry.register(ConnectorTestExecutor(mock_conn_service))
    registry.register(NotificationRetryExecutor(mock_notif_service))

    service = ActionService(
        store=action_store,
        policy_engine=policy_engine,
        executor_registry=registry,
        execution_timeout_seconds=2.0,
    )

    return {
        "service": service,
        "action_store": action_store,
        "connector_store": connector_store,
        "notification_store": notification_store,
        "incident_repo": incident_repo,
        "incident_service": incident_service,
        "mock_conn_service": mock_conn_service,
        "mock_notif_service": mock_notif_service,
    }


@pytest.mark.asyncio
async def test_full_lifecycle_propose_approve_execute(service_env):
    """Test standard happy path: Propose -> Approve -> Execute -> SUCCEEDED."""
    service = service_env["service"]

    # 1. Propose
    action = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        parameters={},
        operator_claim="operator:admin",
        incident_id="inc-1",
    )
    assert action.policy_status == PolicyStatus.ALLOWED
    assert action.approval_status == ApprovalStatus.PENDING
    assert action.execution_status == ExecutionStatus.NOT_STARTED

    # 2. Approve
    approved = service.approve_action(action.action_id, "operator:admin", "Looks safe")
    assert approved.approval_status == ApprovalStatus.APPROVED
    assert approved.approved_by_claim == "operator:admin"

    # 3. Execute
    executed = await service.execute_action(action.action_id)
    assert executed.execution_status == ExecutionStatus.SUCCEEDED
    assert executed.execution_result["status"] == "success"

    # Verify complete audit history
    audits = service.list_audits(action.action_id)
    event_types = [a.event_type for a in audits]
    assert "PROPOSED" in event_types
    assert "POLICY_EVALUATED" in event_types
    assert "APPROVED" in event_types
    assert "EXECUTION_STARTED" in event_types
    assert "EXECUTION_COMPLETED" in event_types


@pytest.mark.asyncio
async def test_incident_closes_between_approval_and_execute(service_env):
    """Test race condition: Incident is closed after approval -> execution is ABORTED."""
    service = service_env["service"]
    incident_repo = service_env["incident_repo"]

    # Propose and approve
    action = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        parameters={},
        operator_claim="operator:admin",
        incident_id="inc-1",
    )
    service.approve_action(action.action_id, "operator:admin")

    # Incident closes before execute
    inc = incident_repo.get_by_id("inc-1")
    inc.status = IncidentStatus.RESOLVED
    incident_repo.update(inc)

    # Attempt execute
    with pytest.raises(ActionExecutionError) as exc_info:
        await service.execute_action(action.action_id)

    assert "RESOLVED" in str(exc_info.value)

    # Action is permanently ABORTED
    updated = service.get_action(action.action_id)
    assert updated.execution_status == ExecutionStatus.ABORTED
    assert updated.policy_status == PolicyStatus.DENIED

    audits = service.list_audits(action.action_id)
    assert any(a.event_type == "POLICY_REVALIDATION_FAILED" for a in audits)


@pytest.mark.asyncio
async def test_notification_stops_being_failed_before_retry(service_env):
    """Test race condition: Notification changes status before retry -> execution is ABORTED."""
    service = service_env["service"]
    mock_notif_service = service_env["mock_notif_service"]

    # Propose and approve
    action = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.RETRY_NOTIFICATION,
        target_type=TargetType.NOTIFICATION,
        target_id="notif-1",
        parameters={},
        operator_claim="operator:admin",
    )
    service.approve_action(action.action_id, "operator:admin")

    # Mock atomic retry reporting state drift
    mock_resp = MagicMock(spec=NotificationResponse)
    mock_resp.delivery_status = DeliveryStatus.DELIVERED
    mock_notif_service.atomic_retry_notification.return_value = (False, mock_resp, DeliveryStatus.DELIVERED)

    # Attempt execute
    with pytest.raises(ActionExecutionError) as exc_info:
        await service.execute_action(action.action_id)

    assert "no longer in FAILED state" in str(exc_info.value)

    updated = service.get_action(action.action_id)
    assert updated.execution_status == ExecutionStatus.ABORTED
    assert "no longer in FAILED state" in updated.failure_reason

    audits = service.list_audits(action.action_id)
    assert any(a.event_type == "PREREQUISITE_CONFLICT_ABORTED" for a in audits)


@pytest.mark.asyncio
async def test_concurrent_proposals_for_same_target(service_env):
    """Test that two simultaneous proposals for the same target result in one 409 conflict."""
    service = service_env["service"]

    # First proposal succeeds
    act1 = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        parameters={},
        operator_claim="operator:admin",
    )
    assert act1.policy_status == PolicyStatus.ALLOWED

    # Second proposal denied by policy (or store integrity check)
    act2 = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        parameters={},
        operator_claim="operator:admin",
    )
    assert act2.policy_status == PolicyStatus.DENIED
    assert "already in flight" in act2.policy_denial_reason


@pytest.mark.asyncio
async def test_concurrent_execution_claims(service_env):
    """Test that concurrent executions of the same action allow only one winner."""
    service = service_env["service"]

    action = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        parameters={},
        operator_claim="operator:admin",
    )
    service.approve_action(action.action_id, "operator:admin")

    # Run two execute_action calls concurrently
    results = await asyncio.gather(
        service.execute_action(action.action_id),
        service.execute_action(action.action_id),
        return_exceptions=True,
    )

    success_count = sum(1 for r in results if not isinstance(r, Exception))
    failure_count = sum(1 for r in results if isinstance(r, Exception))

    # Exactly one must succeed, the other fails due to compare-and-set claim lock
    assert success_count == 1
    assert failure_count == 1


@pytest.mark.asyncio
async def test_retry_notification_prerequisite_conflict_real_store(tmp_path):
    """Test exact prerequisite conflict timing against real SQLite stores (no mocks):

    - notification starts FAILED
    - SafeAction proposed and approved
    - notification changed to PENDING before SafeAction execute (deliberate prerequisite change)
    - SafeAction execute attempts conditional retry
    - zero rows affected
    - action becomes ABORTED
    - approval remains APPROVED
    - completed_at populated
    - PREREQUISITE_CONFLICT_ABORTED recorded exactly once
    - no EXECUTION_COMPLETED success event
    - notification is not mutated a second time
    """
    db_file = str(tmp_path / "real_store_conflict.db")
    action_store = SqliteActionStore(db_path=db_file)
    notif_store = SqliteNotificationStore(db_path=db_file)
    conn_store = SqliteConnectorStore(db_path=db_file)
    incident_repo = InMemoryIncidentRepository()
    incident_service = IncidentService(repository=incident_repo)

    now = datetime.now(timezone.utc)
    with action_store._lock:
        cursor = action_store._conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO projects (
                project_id, name, workspace_path, normalized_path, is_git, status, created_at, updated_at
            ) VALUES ('proj-real', 'Real Project', '/w', '/w', 1, 'ready', '2026-01-01', '2026-01-01');
            """
        )
        action_store._conn.commit()

    notif = Notification(
        notification_id="notif-real-1",
        project_id="proj-real",
        incident_id=None,
        subscription_id=None,
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Real Fail",
        message="Real Fail Msg",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="http://webhook",
        delivery_status=DeliveryStatus.FAILED,
        read_status=ReadStatus.UNREAD,
        attempt_count=3,
        created_at=now,
        updated_at=now,
    )
    notif_store.create_notification(notif)

    real_notif_service = NotificationService(store=notif_store, project_store=MagicMock())
    policy_engine = ActionPolicyEngine(
        action_store=action_store,
        connector_store=conn_store,
        notification_store=notif_store,
        incident_service=incident_service,
    )
    registry = ActionExecutorRegistry()
    registry.register(NotificationRetryExecutor(notification_service=real_notif_service))

    service = ActionService(
        store=action_store,
        policy_engine=policy_engine,
        executor_registry=registry,
    )

    # 1. Propose
    act = service.propose_action(
        project_id="proj-real",
        action_type=ActionType.RETRY_NOTIFICATION,
        target_type=TargetType.NOTIFICATION,
        target_id="notif-real-1",
        parameters={},
        operator_claim="operator:admin",
    )
    assert act.policy_status == PolicyStatus.ALLOWED
    assert act.approval_status == ApprovalStatus.PENDING
    assert act.execution_status == ExecutionStatus.NOT_STARTED

    # 2. Approve
    service.approve_action(act.action_id, "operator:admin")

    # 3. Deliberately mutate notification to PENDING before execute
    # (Simulating external retry, delivery worker pick-up, etc.)
    with notif_store._lock:
        cursor = notif_store._conn.cursor()
        cursor.execute(
            "UPDATE notifications SET delivery_status = 'pending', attempt_count = 0 WHERE notification_id = 'notif-real-1';"
        )
        notif_store._conn.commit()

    # 4. Attempt SafeAction execute
    with pytest.raises(ActionExecutionError) as exc_info:
        await service.execute_action(act.action_id)

    assert "no longer in FAILED state" in str(exc_info.value)

    # 5. Authoritative action state: ABORTED, approval remains APPROVED, completed_at populated
    stored = service.get_action(act.action_id)
    assert stored.approval_status == ApprovalStatus.APPROVED
    assert stored.execution_status == ExecutionStatus.ABORTED
    assert stored.completed_at is not None
    assert "no longer in FAILED state" in stored.failure_reason
    assert stored.execution_result == {"current_state": "pending"}

    # 6. Audits contain exactly one PREREQUISITE_CONFLICT_ABORTED, no EXECUTION_COMPLETED
    audits = service.list_audits(act.action_id)
    event_types = [a.event_type for a in audits]
    assert "PREREQUISITE_CONFLICT_ABORTED" in event_types
    assert "EXECUTION_COMPLETED" not in event_types
    assert event_types.count("PREREQUISITE_CONFLICT_ABORTED") == 1

    # 7. Notification not mutated a second time
    n_stored = notif_store.get_notification("notif-real-1")
    assert n_stored.delivery_status == DeliveryStatus.PENDING
    assert n_stored.attempt_count == 0


@pytest.mark.asyncio
async def test_prerequisite_conflict_cannot_strand_action_in_executing(service_env):
    """Prove that a known prerequisite conflict cannot strand an action in EXECUTING."""
    service = service_env["service"]
    mock_notif_service = service_env["mock_notif_service"]

    action = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.RETRY_NOTIFICATION,
        target_type=TargetType.NOTIFICATION,
        target_id="notif-1",
        parameters={},
        operator_claim="operator:admin",
    )
    service.approve_action(action.action_id, "operator:admin")

    # Prerequisite drift
    mock_resp = MagicMock(spec=NotificationResponse)
    mock_resp.delivery_status = DeliveryStatus.PENDING
    mock_notif_service.atomic_retry_notification.return_value = (False, mock_resp, DeliveryStatus.PENDING)

    with pytest.raises(ActionExecutionError):
        await service.execute_action(action.action_id)

    # State must be terminal ABORTED, not stuck in EXECUTING
    final_act = service.get_action(action.action_id)
    assert final_act.execution_status != ExecutionStatus.EXECUTING
    assert final_act.execution_status == ExecutionStatus.ABORTED


def test_service_startup_reconciliation_no_executor_side_effects(service_env):
    """Prove startup reconciliation transitions orphaned EXECUTING action to ABORTED without running executors."""
    service = service_env["service"]
    store = service_env["action_store"]
    mock_conn_service = service_env["mock_conn_service"]
    mock_notif_service = service_env["mock_notif_service"]

    # Propose and approve an action
    action = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.RETRY_NOTIFICATION,
        target_type=TargetType.NOTIFICATION,
        target_id="notif-1",
        parameters={},
        operator_claim="operator:admin",
    )
    service.approve_action(action.action_id, "operator:admin")

    # Simulate an interrupted crash/restart while EXECUTING
    now = datetime.now(timezone.utc)
    claimed, act_claimed, reason = store.claim_action_for_execution(action.action_id, action.fingerprint, now)
    assert claimed
    assert act_claimed.execution_status == ExecutionStatus.EXECUTING

    # Reset any mock call counts
    mock_notif_service.atomic_retry_notification.reset_mock()
    mock_conn_service.test_connector.reset_mock()

    # Reconcile on startup
    reconciled = service.reconcile_interrupted_executions()
    assert len(reconciled) == 1
    assert reconciled[0].action_id == action.action_id
    assert reconciled[0].execution_status == ExecutionStatus.ABORTED

    # Ensure no executor or side effect was invoked!
    mock_notif_service.atomic_retry_notification.assert_not_called()
    mock_conn_service.test_connector.assert_not_called()

    # Verify action in store is terminal ABORTED with failure reason and audit event
    stored = service.get_action(action.action_id)
    assert stored.approval_status == ApprovalStatus.APPROVED
    assert stored.execution_status == ExecutionStatus.ABORTED
    assert stored.failure_reason == "Execution interrupted across backend restart."
    assert stored.completed_at is not None

    audits = service.list_audits(action.action_id)
    event_types = [a.event_type for a in audits]
    assert "EXECUTION_ABORTED_ON_RESTART" in event_types
    assert "EXECUTION_COMPLETED" not in event_types
    restart_audit = [a for a in audits if a.event_type == "EXECUTION_ABORTED_ON_RESTART"][0]
    assert restart_audit.payload.get("reason") == "Execution interrupted across backend restart."

    # Verify active-target lock was released: proposing again on the same target succeeds
    new_action = service.propose_action(
        project_id="proj-1",
        action_type=ActionType.RETRY_NOTIFICATION,
        target_type=TargetType.NOTIFICATION,
        target_id="notif-1",
        parameters={},
        operator_claim="operator:admin",
    )
    assert new_action.action_id != action.action_id
    assert new_action.policy_status == PolicyStatus.ALLOWED


