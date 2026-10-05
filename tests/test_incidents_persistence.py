"""Automated integration tests for Incident SQLite persistence across simulated restarts."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient

from app.actions.dependencies import (
    close_action_store,
    get_action_service,
    set_custom_action_db_path,
)
from app.actions.models import (
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    RiskLevel,
    TargetType,
)
from app.connectors.dependencies import (
    close_connector_store,
    set_custom_connector_db_path,
)
from app.connectors.models import Connector, ConnectorConfig, ConnectorStatus, ConnectorType
from app.connectors.store import SqliteConnectorStore
from app.incidents.dependencies import (
    close_incident_repository,
    get_incident_repository,
    get_incident_service,
    reset_incident_state,
    set_custom_incident_db_path,
)
from app.incidents.models import IncidentStatus, Severity
from app.incidents.repository import SqliteIncidentRepository
from app.main import app
from app.notifications.dependencies import (
    close_notification_store,
    get_notification_service,
    set_custom_notification_db_path,
)
from app.notifications.models import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationType,
    ReadStatus,
    SubscriptionCreateRequest,
)
from app.notifications.store import SqliteNotificationStore
from app.projects.dependencies import (
    close_project_store,
    set_custom_project_db_path,
)
from app.projects.models import Project, ProjectStatus
from app.projects.storage import SqliteProjectStore


@pytest.fixture
def isolated_db(tmp_path):
    """Provides an isolated database path, resetting state before and after."""
    db_file = str(tmp_path / "incidents_persistence_test.db")
    set_custom_project_db_path(db_file)
    set_custom_connector_db_path(db_file)
    set_custom_notification_db_path(db_file)
    set_custom_action_db_path(db_file)
    set_custom_incident_db_path(db_file)

    yield db_file

    close_action_store()
    close_notification_store()
    close_connector_store()
    close_project_store()
    close_incident_repository()

    set_custom_project_db_path(None)
    set_custom_connector_db_path(None)
    set_custom_notification_db_path(None)
    set_custom_action_db_path(None)
    set_custom_incident_db_path(None)


def test_incident_crud_and_status_transition_persists_across_restart(isolated_db):
    """Verify that incidents created via POST /incidents and status transitions persist across restarts:

    - POST /incidents creates incident
    - GET /incidents returns it
    - GET /incidents/{id} returns it
    - status transition: OPEN -> INVESTIGATING
    - restart application / repository
    - incident still exists with INVESTIGATING status
    - all fields (id, title, summary, severity, status, service, environment, project_id, timestamps) round-trip exactly
    - status transition: INVESTIGATING -> RESOLVED
    - second restart application / repository
    - incident still exists with RESOLVED status
    """
    # 1. First process run: create incident
    with TestClient(app) as client:
        create_payload = {
            "title": "Database connection pool exhaustion",
            "summary": "Connection pool timeout reached under spike load.",
            "severity": "critical",
            "service": "order-service",
            "environment": "production",
            "project_id": "proj-persisted-1",
        }
        res = client.post("/incidents", json=create_payload)
        assert res.status_code == 201
        data = res.json()
        incident_id = data["id"]
        assert data["title"] == create_payload["title"]
        assert data["summary"] == create_payload["summary"]
        assert data["severity"] == "critical"
        assert data["status"] == "open"
        assert data["service"] == "order-service"
        assert data["environment"] == "production"
        assert data["project_id"] == "proj-persisted-1"
        created_at_orig = data["created_at"]
        updated_at_orig = data["updated_at"]

        # Verify list and get before restart
        list_res = client.get("/incidents")
        assert list_res.status_code == 200
        assert any(i["id"] == incident_id for i in list_res.json())

        get_res = client.get(f"/incidents/{incident_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == incident_id

        # Update status to investigating
        patch_res = client.patch(f"/incidents/{incident_id}/status", json={"status": "investigating"})
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "investigating"
        updated_at_investigating = patch_res.json()["updated_at"]

    # 2. Simulate complete backend restart: close repository and re-point to same DB
    close_incident_repository()
    set_custom_incident_db_path(isolated_db)

    with TestClient(app) as client_restart1:
        # GET /incidents after restart
        list_res = client_restart1.get("/incidents")
        assert list_res.status_code == 200
        items = list_res.json()
        match = next((i for i in items if i["id"] == incident_id), None)
        assert match is not None
        assert match["title"] == "Database connection pool exhaustion"
        assert match["summary"] == "Connection pool timeout reached under spike load."
        assert match["severity"] == "critical"
        assert match["status"] == "investigating"
        assert match["service"] == "order-service"
        assert match["environment"] == "production"
        assert match["project_id"] == "proj-persisted-1"
        assert match["created_at"] == created_at_orig
        assert match["updated_at"] == updated_at_investigating

        # Direct GET /incidents/{id}
        get_res = client_restart1.get(f"/incidents/{incident_id}")
        assert get_res.status_code == 200
        direct_data = get_res.json()
        assert direct_data["id"] == incident_id
        assert direct_data["status"] == "investigating"

        # Further transition across restart: investigating -> resolved
        patch_res = client_restart1.patch(f"/incidents/{incident_id}/status", json={"status": "resolved"})
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "resolved"

    # 3. Simulate second backend restart: verify resolved persists
    close_incident_repository()
    set_custom_incident_db_path(isolated_db)

    with TestClient(app) as client_restart2:
        get_res = client_restart2.get(f"/incidents/{incident_id}")
        assert get_res.status_code == 200
        final_data = get_res.json()
        assert final_data["status"] == "resolved"
        assert final_data["title"] == "Database connection pool exhaustion"


def test_multiple_incidents_persist_without_duplication(isolated_db):
    """Verify that multiple incidents persist across restarts without duplication or loss."""
    ids = []
    with TestClient(app) as client:
        for idx in range(3):
            res = client.post(
                "/incidents",
                json={
                    "title": f"Incident {idx}",
                    "summary": f"Summary {idx}",
                    "severity": "medium",
                    "service": "api-gateway",
                    "environment": "staging",
                    "project_id": "proj-multi",
                },
            )
            assert res.status_code == 201
            ids.append(res.json()["id"])

        list_res = client.get("/incidents")
        assert len([i for i in list_res.json() if i["id"] in ids]) == 3

    # Restart 1
    close_incident_repository()
    set_custom_incident_db_path(isolated_db)

    with TestClient(app) as client:
        list_res = client.get("/incidents")
        persisted = [i for i in list_res.json() if i["id"] in ids]
        assert len(persisted) == 3
        assert [p["id"] for p in persisted] == ids

    # Restart 2: ensure no duplication
    close_incident_repository()
    set_custom_incident_db_path(isolated_db)

    with TestClient(app) as client:
        list_res = client.get("/incidents")
        persisted = [i for i in list_res.json() if i["id"] in ids]
        assert len(persisted) == 3


def test_safe_action_bound_to_incident_resolves_across_restart(isolated_db):
    """Verify that a SafeAction bound to an incident can resolve its incident across restart:

    - Create incident
    - Propose SafeAction bound to incident
    - Approve SafeAction
    - Restart backend
    - SafeAction policy check pre-execution still succeeds because incident persists
    - Execute SafeAction succeeds
    """
    now = datetime.now(timezone.utc)

    # Seed project & connector in DB
    p_store = SqliteProjectStore(isolated_db)
    p_store.create_project(
        Project(
            project_id="proj-safe-action",
            name="Action Project",
            workspace_path="/tmp/action",
            normalized_path="/tmp/action",
            is_git=False,
            status=ProjectStatus.READY,
            created_at=now,
            updated_at=now,
        )
    )
    c_store = SqliteConnectorStore(isolated_db)
    c_store.create_connector(
        Connector(
            connector_id="conn-safe-1",
            project_id="proj-safe-action",
            name="Connector 1",
            connector_type=ConnectorType.HTTP_POLLER,
            config=ConnectorConfig(url="http://127.0.0.1:8000/health"),
            status=ConnectorStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )

    action_id = None
    incident_id = None

    with TestClient(app) as client:
        # Create incident
        inc_res = client.post(
            "/incidents",
            json={
                "title": "Connector failure incident",
                "summary": "Health probe timeout",
                "severity": "high",
                "service": "poller",
                "environment": "production",
                "project_id": "proj-safe-action",
            },
        )
        assert inc_res.status_code == 201
        incident_id = inc_res.json()["id"]

        # Propose safe action referencing the incident
        prop_res = client.post(
            "/actions/propose",
            json={
                "project_id": "proj-safe-action",
                "incident_id": incident_id,
                "action_type": "test_connector",
                "target_type": "connector",
                "target_id": "conn-safe-1",
                "parameters": {},
                "operator_claim": "operator:admin",
            },
        )
        assert prop_res.status_code == 201
        action_id = prop_res.json()["action_id"]

        # Approve safe action
        appr_res = client.post(
            f"/actions/{action_id}/approve",
            json={"operator_claim": "operator:admin", "comment": "Approved test"},
        )
        assert appr_res.status_code == 200

    # Simulate complete backend restart
    close_action_store()
    close_incident_repository()
    close_connector_store()
    close_project_store()

    set_custom_action_db_path(isolated_db)
    set_custom_incident_db_path(isolated_db)
    set_custom_connector_db_path(isolated_db)
    set_custom_project_db_path(isolated_db)

    with TestClient(app) as client:
        # 1. Incident is still found via GET /incidents/{incident_id}
        inc_get = client.get(f"/incidents/{incident_id}")
        assert inc_get.status_code == 200

        # 2. SafeAction is still found via GET /actions/{action_id}
        act_get = client.get(f"/actions/{action_id}")
        assert act_get.status_code == 200
        assert act_get.json()["incident_id"] == incident_id

        # 3. SafeAction executes cleanly (Policy check #2 finds the persisted incident)
        mock_resp = httpx.Response(200, json={"status": "ok"})
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            exec_res = client.post(f"/actions/{action_id}/execute")
            assert exec_res.status_code == 200
            assert exec_res.json()["execution_status"] == "succeeded"


def test_notification_bound_to_incident_persists_link_across_restart(isolated_db):
    """Verify that notifications created for incidents maintain durable referential link across restarts."""
    now = datetime.now(timezone.utc)
    p_store = SqliteProjectStore(isolated_db)
    p_store.create_project(
        Project(
            project_id="proj-notif",
            name="Notif Project",
            workspace_path="/tmp/notif",
            normalized_path="/tmp/notif",
            is_git=False,
            status=ProjectStatus.READY,
            created_at=now,
            updated_at=now,
        )
    )

    incident_id = None
    notification_id = None

    with TestClient(app) as client:
        # Create subscription
        sub_res = client.post(
            "/notifications/subscriptions",
            json={
                "project_id": "proj-notif",
                "name": "Webhook Sub",
                "channel": "webhook",
                "destination_config": {"url": "http://127.0.0.1:9999/hook"},
                "min_severity": "low",
                "enabled": True,
            },
        )
        assert sub_res.status_code == 201

        # Create incident
        inc_res = client.post(
            "/incidents",
            json={
                "title": "Notification test incident",
                "summary": "Verifying notification persistence link",
                "severity": "high",
                "service": "api",
                "environment": "production",
                "project_id": "proj-notif",
            },
        )
        assert inc_res.status_code == 201
        incident_id = inc_res.json()["id"]

        # Check notifications generated for incident
        notifs_res = client.get(f"/notifications?project_id=proj-notif")
        assert notifs_res.status_code == 200
        notifs = notifs_res.json()
        matching_notif = next((n for n in notifs if n.get("incident_id") == incident_id), None)
        assert matching_notif is not None
        notification_id = matching_notif["notification_id"]

    # Restart
    close_incident_repository()
    close_notification_store()
    close_project_store()

    set_custom_incident_db_path(isolated_db)
    set_custom_notification_db_path(isolated_db)
    set_custom_project_db_path(isolated_db)

    with TestClient(app) as client:
        # Verify incident exists
        inc_get = client.get(f"/incidents/{incident_id}")
        assert inc_get.status_code == 200
        assert inc_get.json()["id"] == incident_id

        # Verify notification exists and still references incident
        notif_get = client.get(f"/notifications/{notification_id}")
        assert notif_get.status_code == 200
        assert notif_get.json()["incident_id"] == incident_id


@pytest.mark.asyncio
async def test_automatic_detection_incident_persists_across_restart(isolated_db):
    """Verify that an automatically created detection incident persists in SQLite across restart."""
    from app.detection.engine import DetectionEngine
    from app.incidents.repository import SqliteIncidentRepository
    from app.incidents.service import IncidentService
    from app.telemetry.repository import InMemoryEvidenceRepository
    from app.watcher.buffer import RollingTelemetryBuffer
    from app.watcher.models import SignalType, TelemetryEvent
    from app.watcher.service import WatcherService
    from app.watcher.storage import SqliteTelemetryStore

    now = datetime.now(timezone.utc)
    storage = SqliteTelemetryStore(db_path=isolated_db)
    buffer = RollingTelemetryBuffer(capacity=50)

    # Repository pointing to SQLite DB
    inc_repo = SqliteIncidentRepository(db_path=isolated_db)
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    watcher = WatcherService(
        buffer=buffer,
        storage=storage,
        detection_engine=engine,
    )

    # Ingest event that triggers detection rule
    evt = TelemetryEvent(
        event_id="det-evt-1",
        project_id="proj-auto-det",
        service="inventory-svc",
        environment="production",
        signal_type=SignalType.LOG,
        source="test",
        timestamp=now,
        ingested_at=now,
        level="ERROR",
        event_type="out_of_stock_critical",
        message="Inventory exhausted for SKU 9999",
        endpoint="/stock/deduct",
    )
    await watcher.ingest_event(evt)

    # Verify detection engine created an incident
    incidents = inc_service.list_incidents()
    matching = [i for i in incidents if i.service == "inventory-svc"]
    assert len(matching) == 1
    det_incident_id = matching[0].id
    assert matching[0].status == IncidentStatus.OPEN
    assert matching[0].project_id == "proj-auto-det"

    # Close repository connection to simulate backend shutdown
    inc_repo.close()
    storage.close()

    # Re-open repository from same SQLite DB to simulate restart
    fresh_repo = SqliteIncidentRepository(db_path=isolated_db)
    fresh_service = IncidentService(fresh_repo)

    persisted_incidents = fresh_service.list_incidents()
    persisted_matching = [i for i in persisted_incidents if i.id == det_incident_id]
    assert len(persisted_matching) == 1
    assert persisted_matching[0].service == "inventory-svc"
    assert persisted_matching[0].status == IncidentStatus.OPEN
    assert persisted_matching[0].project_id == "proj-auto-det"
    assert persisted_matching[0].created_at is not None

    fresh_repo.close()


def test_full_stage18_failure_sequence_reproduction(isolated_db):
    """Regression test reproducing the full Stage 18 failure sequence:
    - start app on temp SQLite DB
    - create stage14-alpha incident A
    - transition A to investigating
    - create incident B
    - restart app
    - verify A/B exist
    - perform SafeAction TEST_CONNECTOR flow
    - perform RETRY_NOTIFICATION flow
    - perform prerequisite-conflict flow
    - perform desktop/poller-style list calls
    - restart app again
    - verify A/B STILL exist
    - verify scoped GET /incidents?project_id=stage14-alpha returns both
    - verify direct GET by ID returns both
    """
    now = datetime.now(timezone.utc)
    proj_id = "stage14-alpha"

    # Seed project
    p_store = SqliteProjectStore(isolated_db)
    p_store.create_project(
        Project(
            project_id=proj_id,
            name="Stage 14 Alpha",
            workspace_path="/tmp/stage14",
            normalized_path="/tmp/stage14",
            is_git=False,
            status=ProjectStatus.READY,
            created_at=now,
            updated_at=now,
        )
    )

    # Seed connector
    c_store = SqliteConnectorStore(isolated_db)
    c_store.create_connector(
        Connector(
            connector_id="conn-stage14-1",
            project_id=proj_id,
            name="Alpha Health Poller",
            connector_type=ConnectorType.HTTP_POLLER,
            config=ConnectorConfig(url="http://127.0.0.1:8000/health"),
            status=ConnectorStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )

    # Seed failed notifications
    n_store = SqliteNotificationStore(isolated_db)
    n_store.create_notification(
        Notification(
            notification_id="notif-retry-1",
            project_id=proj_id,
            incident_id=None,
            channel=NotificationChannel.WEBHOOK,
            notification_type=NotificationType.INCIDENT_CREATED,
            severity=Severity.HIGH,
            title="Notification Retry Target",
            message="Initial notification failure",
            payload={},
            recipient="http://127.0.0.1:9999/webhook",
            delivery_status=DeliveryStatus.FAILED,
            read_status=ReadStatus.UNREAD,
            attempt_count=3,
            created_at=now,
            updated_at=now,
        )
    )
    n_store.create_notification(
        Notification(
            notification_id="notif-conflict-1",
            project_id=proj_id,
            incident_id=None,
            channel=NotificationChannel.WEBHOOK,
            notification_type=NotificationType.INCIDENT_CREATED,
            severity=Severity.HIGH,
            title="Notification Conflict Target",
            message="Prerequisite conflict target",
            payload={},
            recipient="http://127.0.0.1:9999/webhook",
            delivery_status=DeliveryStatus.FAILED,
            read_status=ReadStatus.UNREAD,
            attempt_count=3,
            created_at=now,
            updated_at=now,
        )
    )

    incident_a_id = None
    incident_b_id = None

    # Step 1: Create incident A and transition to investigating; create incident B
    with TestClient(app) as client:
        res_a = client.post(
            "/incidents",
            json={
                "title": "Incident A - DB saturation",
                "summary": "Database saturation in alpha",
                "severity": "high",
                "service": "database",
                "environment": "production",
                "project_id": proj_id,
            },
        )
        assert res_a.status_code == 201
        incident_a_id = res_a.json()["id"]

        patch_a = client.patch(f"/incidents/{incident_a_id}/status", json={"status": "investigating"})
        assert patch_a.status_code == 200
        assert patch_a.json()["status"] == "investigating"

        res_b = client.post(
            "/incidents",
            json={
                "title": "Incident B - Memory leak",
                "summary": "Memory leak detected",
                "severity": "medium",
                "service": "worker",
                "environment": "production",
                "project_id": proj_id,
            },
        )
        assert res_b.status_code == 201
        incident_b_id = res_b.json()["id"]

    # Step 2: Restart app 1
    close_action_store()
    close_incident_repository()
    close_notification_store()
    close_connector_store()
    close_project_store()

    set_custom_action_db_path(isolated_db)
    set_custom_incident_db_path(isolated_db)
    set_custom_notification_db_path(isolated_db)
    set_custom_connector_db_path(isolated_db)
    set_custom_project_db_path(isolated_db)

    # Step 3: Verify A/B exist
    with TestClient(app) as client:
        res_get_a = client.get(f"/incidents/{incident_a_id}")
        assert res_get_a.status_code == 200
        assert res_get_a.json()["status"] == "investigating"

        res_get_b = client.get(f"/incidents/{incident_b_id}")
        assert res_get_b.status_code == 200
        assert res_get_b.json()["status"] == "open"

        # Perform SafeAction TEST_CONNECTOR flow
        prop_conn = client.post(
            "/actions/propose",
            json={
                "project_id": proj_id,
                "incident_id": incident_a_id,
                "action_type": "test_connector",
                "target_type": "connector",
                "target_id": "conn-stage14-1",
                "parameters": {},
                "operator_claim": "operator:tester",
            },
        )
        assert prop_conn.status_code == 201
        conn_action_id = prop_conn.json()["action_id"]

        appr_conn = client.post(
            f"/actions/{conn_action_id}/approve",
            json={"operator_claim": "operator:tester", "comment": "Approved test"},
        )
        assert appr_conn.status_code == 200

        mock_resp = httpx.Response(200, json={"status": "ok"})
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            exec_conn = client.post(f"/actions/{conn_action_id}/execute")
            assert exec_conn.status_code == 200
            assert exec_conn.json()["execution_status"] == "succeeded"

        # Perform RETRY_NOTIFICATION flow
        prop_notif = client.post(
            "/actions/propose",
            json={
                "project_id": proj_id,
                "incident_id": incident_b_id,
                "action_type": "retry_notification",
                "target_type": "notification",
                "target_id": "notif-retry-1",
                "parameters": {},
                "operator_claim": "operator:tester",
            },
        )
        assert prop_notif.status_code == 201
        notif_action_id = prop_notif.json()["action_id"]

        appr_notif = client.post(
            f"/actions/{notif_action_id}/approve",
            json={"operator_claim": "operator:tester", "comment": "Approved retry"},
        )
        assert appr_notif.status_code == 200

        exec_notif = client.post(f"/actions/{notif_action_id}/execute")
        assert exec_notif.status_code == 200
        assert exec_notif.json()["execution_status"] == "succeeded"

        # Perform prerequisite-conflict flow
        prop_conflict = client.post(
            "/actions/propose",
            json={
                "project_id": proj_id,
                "incident_id": incident_a_id,
                "action_type": "retry_notification",
                "target_type": "notification",
                "target_id": "notif-conflict-1",
                "parameters": {},
                "operator_claim": "operator:tester",
            },
        )
        assert prop_conflict.status_code == 201
        conflict_action_id = prop_conflict.json()["action_id"]

        appr_conflict = client.post(
            f"/actions/{conflict_action_id}/approve",
            json={"operator_claim": "operator:tester", "comment": "Approved retry"},
        )
        assert appr_conflict.status_code == 200

        # Change prerequisite immediately before execution: mark delivery_status to DELIVERED
        n_store = SqliteNotificationStore(isolated_db)
        with n_store._lock:
            n_store._conn.execute(
                "UPDATE notifications SET delivery_status = 'delivered' WHERE notification_id = 'notif-conflict-1';"
            )
            n_store._conn.commit()

        exec_conflict = client.post(f"/actions/{conflict_action_id}/execute")
        assert exec_conflict.status_code == 409

        # Verify conflict action is ABORTED, not executing
        get_conflict = client.get(f"/actions/{conflict_action_id}")
        assert get_conflict.status_code == 200
        assert get_conflict.json()["execution_status"] == "aborted"

        # Perform desktop/poller-style list calls
        inc_list = client.get(f"/incidents?project_id={proj_id}")
        assert inc_list.status_code == 200
        assert len(inc_list.json()) == 2

        act_list = client.get(f"/actions?project_id={proj_id}")
        assert act_list.status_code == 200
        assert len(act_list.json()) == 3

        notif_list = client.get(f"/notifications?project_id={proj_id}")
        assert notif_list.status_code == 200

        all_inc = client.get("/incidents")
        assert all_inc.status_code == 200

        all_act = client.get("/actions")
        assert all_act.status_code == 200

    # Step 4: Restart app again
    close_action_store()
    close_incident_repository()
    close_notification_store()
    close_connector_store()
    close_project_store()

    set_custom_action_db_path(isolated_db)
    set_custom_incident_db_path(isolated_db)
    set_custom_notification_db_path(isolated_db)
    set_custom_connector_db_path(isolated_db)
    set_custom_project_db_path(isolated_db)

    # Step 5: Verify A/B STILL exist
    with TestClient(app) as client:
        # Scoped list returns both
        scoped_res = client.get(f"/incidents?project_id={proj_id}")
        assert scoped_res.status_code == 200
        scoped_items = scoped_res.json()
        assert len([i for i in scoped_items if i["id"] in (incident_a_id, incident_b_id)]) == 2

        # Direct GET by ID returns both with preserved status
        get_a = client.get(f"/incidents/{incident_a_id}")
        assert get_a.status_code == 200
        assert get_a.json()["id"] == incident_a_id
        assert get_a.json()["status"] == "investigating"
        assert get_a.json()["project_id"] == proj_id

        get_b = client.get(f"/incidents/{incident_b_id}")
        assert get_b.status_code == 200
        assert get_b.json()["id"] == incident_b_id
        assert get_b.json()["status"] == "open"
        assert get_b.json()["project_id"] == proj_id


def test_repository_path_never_silently_switches_after_initialization(tmp_path):
    """Test that initialized repository never silently switches its database path."""
    db_path1 = str(tmp_path / "repo1.db")
    db_path2 = str(tmp_path / "repo2.db")

    set_custom_incident_db_path(db_path1)
    repo1 = get_incident_repository()
    assert repo1.db_path == str(Path(db_path1).resolve())

    # Attempting to call get_incident_repository with different db_path without resetting
    # must NOT silently change the active repository singleton's path
    repo2 = get_incident_repository(db_path=db_path2)
    assert repo2 is repo1
    assert repo2.db_path == str(Path(db_path1).resolve())

    # Only explicit close + redirect can change path
    close_incident_repository()
    set_custom_incident_db_path(db_path2)
    repo3 = get_incident_repository()
    assert repo3.db_path == str(Path(db_path2).resolve())

    close_incident_repository()
    set_custom_incident_db_path(None)


def test_custom_db_path_cannot_leak_into_production_runtime(tmp_path):
    """Test that a custom DB path used by test fixtures does not leak into production default."""
    custom_db = str(tmp_path / "isolated_leak_test.db")
    set_custom_incident_db_path(custom_db)
    test_repo = get_incident_repository()
    assert test_repo.db_path == str(Path(custom_db).resolve())

    # Test teardown resets to None
    close_incident_repository()
    set_custom_incident_db_path(None)

    # Next access without custom DB returns the production runtime DB
    prod_repo = get_incident_repository()
    expected_prod = str(Path("runtime/sentinelops.db").resolve())
    assert prod_repo.db_path == expected_prod

    close_incident_repository()


def test_reset_helper_cannot_clear_production_db():
    """Verify that clear() and reset_incident_state() raise RuntimeError when targeted at production DB."""
    # 1. SqliteIncidentRepository.clear() direct protection
    prod_repo = SqliteIncidentRepository(db_path="runtime/sentinelops.db")
    try:
        with pytest.raises(RuntimeError, match="Refusing to clear production incident database"):
            prod_repo.clear()
    finally:
        prod_repo.close()

    # 2. reset_incident_state() protection
    close_incident_repository()
    set_custom_incident_db_path(None)
    try:
        with pytest.raises(RuntimeError, match="cannot clear production database"):
            reset_incident_state()
    finally:
        close_incident_repository()


def test_watcher_and_correlation_after_restart_creates_fresh_dependencies(isolated_db):
    """Verify that simulated restart cleanly tears down previous incident repository/service,
    and subsequent watcher/correlation operations use fresh active database connections
    without raising 'Cannot operate on a closed database'.
    """
    from app.correlation.dependencies import get_correlation_engine
    from app.detection.dependencies import get_detection_engine
    from app.watcher.models import SignalType, TelemetryEvent

    now = datetime.now(timezone.utc)
    proj_id = "proj-restart-fresh"

    # Step 1: Initial state before restart
    old_repo = get_incident_repository()
    old_service = get_incident_service()
    det_engine = get_detection_engine()

    # Create pre-restart incident via correlation
    event1 = TelemetryEvent(
        event_id="evt-pre-restart-1",
        project_id=proj_id,
        service="order-service",
        environment="production",
        signal_type=SignalType.LOG,
        source="unit-test",
        timestamp=now,
        ingested_at=now,
        level="ERROR",
        event_type="app_exception",
        message="Database connection error",
        endpoint="/checkout",
    )
    res1 = det_engine.evaluate(event1)
    assert res1.matched is True
    assert res1.incident_id is not None
    pre_incident_id = res1.incident_id

    # Verify incident exists in old repository
    assert old_service.get_incident(pre_incident_id) is not None

    # Step 2: Simulate application shutdown / restart
    close_incident_repository()
    # Explicitly verify the old repository connection is closed
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
        old_repo._conn.execute("SELECT 1;")

    # Re-point to the same isolated DB
    set_custom_incident_db_path(isolated_db)

    # Step 3: Fetch post-restart dependencies
    fresh_repo = get_incident_repository()
    fresh_service = get_incident_service()
    fresh_det_engine = get_detection_engine()

    # Verify fresh objects are NOT the old closed objects
    assert fresh_repo is not old_repo
    assert fresh_service is not old_service
    # Verify fresh connection is open and operable
    fresh_repo._conn.execute("SELECT 1;").fetchone()

    # Step 4: Pre-restart incident is still found via fresh service
    persisted_pre = fresh_service.get_incident(pre_incident_id)
    assert persisted_pre is not None
    assert persisted_pre.id == pre_incident_id

    # Step 5: Post-restart event ingestion through detection & correlation
    # MUST succeed and create an incident without "Cannot operate on a closed database"
    event2 = TelemetryEvent(
        event_id="evt-post-restart-2",
        project_id=proj_id,
        service="payment-service",
        environment="production",
        signal_type=SignalType.LOG,
        source="unit-test",
        timestamp=now + timedelta(seconds=10),
        ingested_at=now + timedelta(seconds=10),
        level="ERROR",
        event_type="app_exception",
        message="Payment gateway error",
        endpoint="/pay",
    )
    res2 = fresh_det_engine.evaluate(event2)
    assert res2.matched is True
    assert res2.incident_id is not None
    post_incident_id = res2.incident_id

    # Verify both incidents exist in the durable database
    assert fresh_service.get_incident(pre_incident_id) is not None
    assert fresh_service.get_incident(post_incident_id) is not None
    assert pre_incident_id != post_incident_id



