"""API integration tests for Safe Actions FastAPI endpoints."""

from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest

from app.actions.dependencies import get_action_store, set_custom_action_db_path
from app.actions.store import SqliteActionStore
from app.connectors.dependencies import set_custom_connector_db_path
from app.connectors.models import Connector, ConnectorConfig, ConnectorStatus, ConnectorType
from app.connectors.store import SqliteConnectorStore
from app.incidents.dependencies import (
    close_incident_repository,
    get_incident_service,
    set_custom_incident_db_path,
)
from app.incidents.models import Incident, IncidentStatus, Severity
from app.main import app
from app.notifications.dependencies import get_notification_store, set_custom_notification_db_path
from app.notifications.models import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationType,
    ReadStatus,
)
from app.notifications.store import SqliteNotificationStore
from app.projects.dependencies import set_custom_project_db_path
from app.projects.models import Project, ProjectStatus
from app.projects.storage import SqliteProjectStore


@pytest.fixture
def client(tmp_path):
    """Sets up a test client with an isolated SQLite DB path."""
    db_file = str(tmp_path / "sentinelops_test.db")
    set_custom_project_db_path(db_file)
    set_custom_connector_db_path(db_file)
    set_custom_notification_db_path(db_file)
    set_custom_action_db_path(db_file)
    set_custom_incident_db_path(db_file)

    now = datetime.now(timezone.utc)
    # Seed project
    p_store = SqliteProjectStore(db_file)
    proj = Project(
        project_id="proj-api",
        name="API Project",
        workspace_path=str(tmp_path),
        normalized_path=str(tmp_path),
        is_git=True,
        status=ProjectStatus.READY,
        created_at=now,
        updated_at=now,
    )
    p_store.create_project(proj)

    # Seed connector
    c_store = SqliteConnectorStore(db_file)
    conn = Connector(
        connector_id="conn-api-1",
        project_id="proj-api",
        name="API Poller",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(url="http://127.0.0.1:8000/health"),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    c_store.create_connector(conn)

    # Seed notification
    n_store = SqliteNotificationStore(db_file)
    notif = Notification(
        notification_id="notif-api-1",
        project_id="proj-api",
        incident_id=None,
        subscription_id=None,
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Alert",
        message="Failed",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="http://webhook",
        delivery_status=DeliveryStatus.FAILED,
        read_status=ReadStatus.UNREAD,
        attempt_count=3,
        created_at=now,
        updated_at=now,
    )
    n_store.create_notification(notif)

    # Seed incident in in-memory incident service
    inc_service = get_incident_service()
    inc_service._repository.clear()
    inc = Incident(
        id="inc-api-1",
        title="API Incident",
        summary="Testing",
        severity=Severity.MEDIUM,
        status=IncidentStatus.OPEN,
        service="api-svc",
        environment="staging",
        created_at=now,
        updated_at=now,
        project_id="proj-api",
    )
    inc_service._repository.create(inc)

    with TestClient(app) as test_client:
        yield test_client

    # Teardown
    close_incident_repository()
    set_custom_incident_db_path(None)
    set_custom_project_db_path(None)
    set_custom_connector_db_path(None)
    set_custom_notification_db_path(None)
    set_custom_action_db_path(None)


def test_api_propose_and_list_actions(client):
    """Test proposing and listing actions via REST API."""
    # Propose valid action
    resp = client.post(
        "/actions/propose",
        json={
            "project_id": "proj-api",
            "action_type": "test_connector",
            "target_type": "connector",
            "target_id": "conn-api-1",
            "parameters": {},
            "operator_claim": "operator:tester",
            "incident_id": "inc-api-1",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["policy_status"] == "allowed"
    assert data["approval_status"] == "pending"
    assert data["execution_status"] == "not_started"
    action_id = data["action_id"]

    # List actions
    list_resp = client.get("/actions?project_id=proj-api")
    assert list_resp.status_code == 200
    actions = list_resp.json()
    assert len(actions) == 1
    assert actions[0]["action_id"] == action_id

    # Get single action
    get_resp = client.get(f"/actions/{action_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["action_id"] == action_id


def test_api_approve_and_audit(client):
    """Test approving an action and querying audit trail."""
    # Propose
    resp = client.post(
        "/actions/propose",
        json={
            "project_id": "proj-api",
            "action_type": "test_connector",
            "target_type": "connector",
            "target_id": "conn-api-1",
            "parameters": {},
            "operator_claim": "operator:tester",
        },
    )
    action_id = resp.json()["action_id"]

    # Approve
    appr_resp = client.post(
        f"/actions/{action_id}/approve",
        json={"operator_claim": "operator:lead", "comment": "Approved for testing"},
    )
    assert appr_resp.status_code == 200
    appr_data = appr_resp.json()
    assert appr_data["approval_status"] == "approved"
    assert appr_data["approved_by_claim"] == "operator:lead"

    # Query audit trail
    audit_resp = client.get(f"/actions/{action_id}/audit")
    assert audit_resp.status_code == 200
    audits = audit_resp.json()
    assert len(audits) >= 3  # PROPOSED, POLICY_EVALUATED, APPROVED
    event_names = [a["event_type"] for a in audits]
    assert "PROPOSED" in event_names
    assert "APPROVED" in event_names


def test_api_reject_action(client):
    """Test rejecting an action."""
    resp = client.post(
        "/actions/propose",
        json={
            "project_id": "proj-api",
            "action_type": "test_connector",
            "target_type": "connector",
            "target_id": "conn-api-1",
            "parameters": {},
            "operator_claim": "operator:tester",
        },
    )
    action_id = resp.json()["action_id"]

    rej_resp = client.post(
        f"/actions/{action_id}/reject",
        json={"operator_claim": "operator:lead", "reason": "Not necessary right now"},
    )
    assert rej_resp.status_code == 200
    rej_data = rej_resp.json()
    assert rej_data["approval_status"] == "rejected"
    assert rej_data["execution_status"] == "aborted"


def test_api_cannot_execute_unapproved_action(client):
    """Test that executing an unapproved action returns 409 Conflict."""
    resp = client.post(
        "/actions/propose",
        json={
            "project_id": "proj-api",
            "action_type": "test_connector",
            "target_type": "connector",
            "target_id": "conn-api-1",
            "parameters": {},
            "operator_claim": "operator:tester",
        },
    )
    action_id = resp.json()["action_id"]

    exec_resp = client.post(f"/actions/{action_id}/execute")
    assert exec_resp.status_code == 409
    assert "not approved" in exec_resp.json()["detail"]


def test_api_execute_retry_notification_prerequisite_conflict_timing(client):
    """Regression test reproducing exact prerequisite-conflict timing:

    - notification starts FAILED
    - SafeAction proposed and approved
    - notification changed to PENDING before SafeAction execute (deliberate prerequisite change)
    - SafeAction execute attempts conditional retry
    - zero rows affected
    - action becomes ABORTED (never stranded in EXECUTING)
    - approval remains APPROVED
    - completed_at is populated
    - PREREQUISITE_CONFLICT_ABORTED recorded exactly once
    - no EXECUTION_COMPLETED success event
    - API does not return 500 (returns 409 Conflict)
    - notification is not mutated a second time
    """
    # 1. Propose SafeAction for the failed notification
    prop_resp = client.post(
        "/actions/propose",
        json={
            "project_id": "proj-api",
            "action_type": "retry_notification",
            "target_type": "notification",
            "target_id": "notif-api-1",
            "parameters": {},
            "operator_claim": "operator:tester",
        },
    )
    assert prop_resp.status_code == 201
    action_data = prop_resp.json()
    action_id = action_data["action_id"]
    assert action_data["policy_status"] == "allowed"
    assert action_data["approval_status"] == "pending"
    assert action_data["execution_status"] == "not_started"

    # 2. Approve SafeAction
    appr_resp = client.post(
        f"/actions/{action_id}/approve",
        json={"operator_claim": "operator:lead", "comment": "Approved for retry"},
    )
    assert appr_resp.status_code == 200
    assert appr_resp.json()["approval_status"] == "approved"

    # 3. Deliberately change prerequisite immediately before execution:
    # Set delivery_status to 'pending' with next_attempt_at in the future so the background
    # worker loop does not race to fail it before execute runs:
    n_store = get_notification_store()
    with n_store._lock:
        cur = n_store._conn.cursor()
        cur.execute(
            "UPDATE notifications SET delivery_status = 'pending', attempt_count = 0, next_attempt_at = '2099-01-01T00:00:00+00:00' WHERE notification_id = 'notif-api-1';"
        )
        n_store._conn.commit()

    # Verify notification is now in PENDING state
    notif_check = client.get("/notifications/notif-api-1")
    assert notif_check.status_code == 200
    assert notif_check.json()["delivery_status"] == "pending"

    # 4. Immediately execute the approved SafeAction
    # MUST NOT return HTTP 500; MUST return HTTP 409 Conflict
    exec_resp = client.post(f"/actions/{action_id}/execute")
    assert exec_resp.status_code == 409
    assert "no longer in FAILED state" in exec_resp.json()["detail"]

    # 5. Authoritative SafeAction state MUST be terminal ABORTED (never EXECUTING)
    get_resp = client.get(f"/actions/{action_id}")
    assert get_resp.status_code == 200
    act_state = get_resp.json()
    assert act_state["approval_status"] == "approved"
    assert act_state["execution_status"] == "aborted"
    assert act_state["completed_at"] is not None
    assert "no longer in FAILED state" in act_state["failure_reason"]
    assert act_state["execution_result"] == {"current_state": "pending"}

    # 6. Verify audit event sequence
    audit_resp = client.get(f"/actions/{action_id}/audit")
    assert audit_resp.status_code == 200
    audits = audit_resp.json()
    event_types = [a["event_type"] for a in audits]

    assert "PROPOSED" in event_types
    assert "POLICY_EVALUATED" in event_types
    assert "APPROVED" in event_types
    assert "EXECUTION_STARTED" in event_types
    assert "PREREQUISITE_CONFLICT_ABORTED" in event_types
    assert "EXECUTION_COMPLETED" not in event_types
    assert event_types.count("PREREQUISITE_CONFLICT_ABORTED") == 1

    # 7. Verify notification was NOT mutated a second time
    notif_get_resp = client.get("/notifications/notif-api-1")
    assert notif_get_resp.status_code == 200
    notif_data = notif_get_resp.json()
    assert notif_data["delivery_status"] == "pending"
    assert notif_data["attempt_count"] == 0


def test_api_lifespan_startup_reconciliation(tmp_path):
    """Test that FastAPI app lifespan reconciles orphaned EXECUTING actions on startup."""
    db_file = str(tmp_path / "lifespan_reconcile_test.db")
    set_custom_project_db_path(db_file)
    set_custom_connector_db_path(db_file)
    set_custom_notification_db_path(db_file)
    set_custom_action_db_path(db_file)
    set_custom_incident_db_path(db_file)

    try:
        now = datetime.now(timezone.utc)
        action_store = SqliteActionStore(db_path=db_file)

        # Insert project
        p_store = SqliteProjectStore(db_file)
        proj = Project(
            project_id="proj-api",
            name="API Project",
            workspace_path=str(tmp_path),
            normalized_path=str(tmp_path),
            is_git=True,
            status=ProjectStatus.READY,
            created_at=now,
            updated_at=now,
        )
        p_store.create_project(proj)

        # Insert connector
        c_store = SqliteConnectorStore(db_file)
        conn = Connector(
            connector_id="conn-api-1",
            project_id="proj-api",
            name="API Poller",
            connector_type=ConnectorType.HTTP_POLLER,
            config=ConnectorConfig(url="http://127.0.0.1:8000/health"),
            status=ConnectorStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        c_store.create_connector(conn)

        # Create, approve, and claim an action to EXECUTING state
        from app.actions.models import (
            ActionType,
            ApprovalStatus,
            ExecutionStatus,
            PolicyStatus,
            RiskLevel,
            SafeAction,
            TargetType,
            compute_action_fingerprint,
        )

        action_id = "stranded-action-api-1"
        fp = compute_action_fingerprint(
            action_type=ActionType.TEST_CONNECTOR,
            target_type=TargetType.CONNECTOR,
            target_id="conn-api-1",
            project_id="proj-api",
            incident_id=None,
            risk_level=RiskLevel.LOW,
            parameters={},
        )
        act = SafeAction(
            action_id=action_id,
            project_id="proj-api",
            incident_id=None,
            action_type=ActionType.TEST_CONNECTOR,
            target_type=TargetType.CONNECTOR,
            target_id="conn-api-1",
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
        action_store.create_action(act, [])
        action_store.approve_action(action_id, "operator:admin", "Approved", now)
        claimed, act_claimed, reason = action_store.claim_action_for_execution(action_id, fp, now)
        assert claimed
        assert act_claimed.execution_status == ExecutionStatus.EXECUTING

        # Start TestClient to trigger lifespan
        with TestClient(app) as client:
            # 1. GET /actions/{action_id} must show ABORTED
            get_resp = client.get(f"/actions/{action_id}")
            assert get_resp.status_code == 200
            data = get_resp.json()
            assert data["approval_status"] == "approved"
            assert data["execution_status"] == "aborted"
            assert data["completed_at"] is not None
            assert data["failure_reason"] == "Execution interrupted across backend restart."

            # 2. GET /actions/{action_id}/audit must show EXECUTION_ABORTED_ON_RESTART
            audit_resp = client.get(f"/actions/{action_id}/audit")
            assert audit_resp.status_code == 200
            audits = audit_resp.json()
            event_types = [a["event_type"] for a in audits]
            assert "EXECUTION_ABORTED_ON_RESTART" in event_types

    finally:
        close_incident_repository()
        set_custom_incident_db_path(None)
        set_custom_project_db_path(None)
        set_custom_connector_db_path(None)
        set_custom_notification_db_path(None)
        set_custom_action_db_path(None)


