"""Unit tests for ActionPolicyEngine deny-by-default rules and proposal-denial semantics."""

from datetime import datetime, timezone
import pytest

from app.actions.models import (
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    TargetType,
)
from app.actions.policy import ActionPolicyEngine
from app.actions.service import ActionService
from app.actions.store import SqliteActionStore
from app.connectors.models import Connector, ConnectorConfig, ConnectorStatus, ConnectorType
from app.connectors.store import SqliteConnectorStore
from app.incidents.models import Incident, IncidentStatus, Severity
from app.incidents.repository import InMemoryIncidentRepository
from app.incidents.service import IncidentService
from app.notifications.models import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationType,
    ReadStatus,
)
from app.notifications.store import SqliteNotificationStore


@pytest.fixture
def policy_env():
    """Sets up an in-memory testing environment for policy tests."""
    action_store = SqliteActionStore(db_path=":memory:")
    connector_store = SqliteConnectorStore(db_path=":memory:")
    notification_store = SqliteNotificationStore(db_path=":memory:")
    incident_repo = InMemoryIncidentRepository()
    incident_service = IncidentService(repository=incident_repo)

    # Seed project in all stores
    now = datetime.now(timezone.utc)
    for s in (action_store, connector_store, notification_store):
        with s._lock:
            cursor = s._conn.cursor()
            cursor.execute(
                """
                INSERT INTO projects (
                    project_id, name, workspace_path, normalized_path, is_git, status, created_at, updated_at
                ) VALUES ('proj-alpha', 'Alpha Project', '/work', '/work', 1, 'ready', '2026-01-01', '2026-01-01');
                """
            )
            s._conn.commit()

    # Seed a connector
    conn = Connector(
        connector_id="conn-alpha",
        project_id="proj-alpha",
        name="Alpha Poller",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(url="http://127.0.0.1:8080/health"),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(conn)

    # Seed a notification
    notif = Notification(
        notification_id="notif-failed",
        project_id="proj-alpha",
        incident_id=None,
        subscription_id=None,
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Test Failed Notif",
        message="Failure",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="http://webhook.site",
        delivery_status=DeliveryStatus.FAILED,
        read_status=ReadStatus.UNREAD,
        attempt_count=3,
        created_at=now,
        updated_at=now,
    )
    notification_store.create_notification(notif)

    # Seed open incident
    inc = Incident(
        id="inc-open",
        title="Open Alert",
        summary="Service down",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="order-svc",
        environment="production",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )
    incident_repo.create(inc)

    # Seed closed incident
    inc_closed = Incident(
        id="inc-closed",
        title="Closed Alert",
        summary="All good",
        severity=Severity.LOW,
        status=IncidentStatus.CLOSED,
        service="order-svc",
        environment="production",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )
    incident_repo.create(inc_closed)

    engine = ActionPolicyEngine(
        action_store=action_store,
        connector_store=connector_store,
        notification_store=notification_store,
        incident_service=incident_service,
    )

    return {
        "engine": engine,
        "action_store": action_store,
        "connector_store": connector_store,
        "notification_store": notification_store,
        "incident_service": incident_service,
    }


def test_policy_allowlist_unknown_type(policy_env):
    """Deny unrecognized action type."""
    engine = policy_env["engine"]
    res = engine.evaluate_proposal(
        action_type="arbitrary_bash_script",  # type: ignore
        target_type=TargetType.CONNECTOR,
        target_id="conn-alpha",
        project_id="proj-alpha",
        parameters={},
    )
    assert not res.is_allowed
    assert "not in the safe action allowlist" in res.reason


def test_policy_target_type_mismatch(policy_env):
    """Deny target type mismatch (e.g. TEST_CONNECTOR on notification)."""
    engine = policy_env["engine"]
    res = engine.evaluate_proposal(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.NOTIFICATION,
        target_id="conn-alpha",
        project_id="proj-alpha",
        parameters={},
    )
    assert not res.is_allowed
    assert "requires target_type 'connector'" in res.reason


def test_policy_parameters_must_be_empty(policy_env):
    """Deny non-empty parameters (Correction 2)."""
    engine = policy_env["engine"]
    res = engine.evaluate_proposal(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-alpha",
        project_id="proj-alpha",
        parameters={"extra": "param", "connector_id": "conn-alpha"},
    )
    assert not res.is_allowed
    assert "accepts no parameters" in res.reason


def test_policy_target_not_found(policy_env):
    """Deny non-existent target."""
    engine = policy_env["engine"]
    res = engine.evaluate_proposal(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="missing-conn",
        project_id="proj-alpha",
        parameters={},
    )
    assert not res.is_allowed
    assert "does not exist" in res.reason


def test_policy_cross_project_target_denied(policy_env):
    """Deny target referencing a different project."""
    engine = policy_env["engine"]
    res = engine.evaluate_proposal(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-alpha",
        project_id="proj-other",
        parameters={},
    )
    assert not res.is_allowed
    assert "belongs to project 'proj-alpha', not 'proj-other'" in res.reason


def test_policy_closed_incident_denied(policy_env):
    """Deny action proposed on a closed incident."""
    engine = policy_env["engine"]
    res = engine.evaluate_proposal(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-alpha",
        project_id="proj-alpha",
        parameters={},
        incident_id="inc-closed",
    )
    assert not res.is_allowed
    assert "terminal status 'CLOSED'" in res.reason


def test_policy_allowed_valid_proposal(policy_env):
    """Allow valid TEST_CONNECTOR and RETRY_NOTIFICATION proposals."""
    engine = policy_env["engine"]
    res1 = engine.evaluate_proposal(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-alpha",
        project_id="proj-alpha",
        parameters={},
        incident_id="inc-open",
    )
    assert res1.is_allowed

    res2 = engine.evaluate_proposal(
        action_type=ActionType.RETRY_NOTIFICATION,
        target_type=TargetType.NOTIFICATION,
        target_id="notif-failed",
        project_id="proj-alpha",
        parameters={},
    )
    assert res2.is_allowed


def test_policy_denied_action_is_terminal_and_does_not_block_valid(policy_env):
    """Verify Correction 1:
    - Denied proposal is terminal (DENIED / CANCELLED / ABORTED).
    - Denied proposal cannot be approved or executed.
    - Denied proposal does NOT block a subsequent valid action for the same target.
    """
    store = policy_env["action_store"]
    engine = policy_env["engine"]
    from app.actions.executors.registry import ActionExecutorRegistry

    service = ActionService(
        store=store,
        policy_engine=engine,
        executor_registry=ActionExecutorRegistry(),
    )

    # 1. Propose invalid action (e.g. non-empty parameters)
    denied_action = service.propose_action(
        project_id="proj-alpha",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-alpha",
        parameters={"illegal": 123},
        operator_claim="operator:admin",
    )
    assert denied_action.policy_status == PolicyStatus.DENIED
    assert denied_action.approval_status == ApprovalStatus.CANCELLED
    assert denied_action.execution_status == ExecutionStatus.ABORTED
    assert "accepts no parameters" in denied_action.policy_denial_reason

    # 2. Cannot approve denied proposal
    from app.actions.store import InvalidActionStateTransitionError

    with pytest.raises(InvalidActionStateTransitionError):
        service.approve_action(denied_action.action_id, "operator:admin")

    # 3. Cannot execute denied proposal
    from app.actions.service import ActionExecutionError

    import asyncio

    with pytest.raises(ActionExecutionError):
        asyncio.run(service.execute_action(denied_action.action_id))

    # 4. Denied action does NOT block subsequent valid action on same target!
    valid_action = service.propose_action(
        project_id="proj-alpha",
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-alpha",
        parameters={},
        operator_claim="operator:admin",
    )
    assert valid_action.policy_status == PolicyStatus.ALLOWED
    assert valid_action.approval_status == ApprovalStatus.PENDING
    assert valid_action.execution_status == ExecutionStatus.NOT_STARTED
