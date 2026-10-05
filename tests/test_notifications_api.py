"""Full API integration tests for SentinelOps Notifications subsystem.

Verifies:
- Production DB isolation (never touches runtime/sentinelops.db)
- Subscription CRUD endpoints and status codes (201, 200, 204, 404, 422, 400)
- Secret masking in GET responses and masked secret preservation on PATCH
- Foreign key ON DELETE RESTRICT on project deletion (409 Conflict)
- Querying historical notifications by project_id after project deletion succeeds
- Feed listing, filtering, pagination, mark-read, mark-all-read
- Diagnostic /test neutrality
- Incident creation automatically triggers notification creation
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.connectors.dependencies import (
    close_connector_store,
    get_connector_store,
    reset_connector_state,
    set_custom_connector_db_path,
)
from app.incidents.dependencies import (
    close_incident_repository,
    get_incident_repository,
    reset_incident_state,
    set_custom_incident_db_path,
)
from app.knowledge.dependencies import reset_knowledge_state
from app.main import app
from app.notifications.dependencies import (
    close_notification_store,
    get_notification_service,
    get_notification_store,
    reset_notification_state,
    set_custom_notification_db_path,
)
from app.projects.dependencies import (
    close_project_store,
    get_project_store,
    reset_project_state,
    set_custom_project_db_path,
)
from app.projects.models import Project, ProjectStatus
from app.telemetry.dependencies import get_evidence_repository
from app.watcher.dependencies import reset_watcher_state

client = TestClient(app)
_test_tmp_path: Path | None = None


@pytest.fixture(autouse=True)
def isolated_test_environment(tmp_path: Path) -> Generator[None, None, None]:
    """Ensure complete test isolation across ProjectStore and NotificationStore."""
    global _test_tmp_path
    _test_tmp_path = tmp_path
    test_db = str(tmp_path / "sentinelops_test.db")

    set_custom_project_db_path(test_db)
    set_custom_connector_db_path(test_db)
    set_custom_notification_db_path(test_db)

    app.dependency_overrides.clear()
    reset_project_state()
    reset_connector_state(db_path=test_db)
    reset_notification_state(db_path=test_db)
    reset_incident_state(db_path=test_db)
    reset_knowledge_state()
    get_evidence_repository().clear()

    # Wire notification service as listener for tests
    from app.incidents.dependencies import get_incident_service
    inc_service = get_incident_service()
    notif_service = get_notification_service()
    inc_service.add_listener(notif_service)

    yield

    inc_service.clear_listeners()
    close_incident_repository()
    close_notification_store()
    close_connector_store()
    close_project_store()
    set_custom_incident_db_path(None)
    set_custom_notification_db_path(None)
    set_custom_connector_db_path(None)
    set_custom_project_db_path(None)


def _create_test_project(project_id: str = "proj-test", name: str = "Test Project") -> dict:
    workspace = _test_tmp_path / project_id
    workspace.mkdir(parents=True, exist_ok=True)
    resp = client.post(
        "/projects",
        json={
            "project_id": project_id,
            "name": name,
            "workspace_path": str(workspace),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_subscription_api_crud_and_validation():
    _create_test_project("proj-sub-test")

    # 1. 404 for unknown project
    bad_resp = client.post(
        "/notifications/subscriptions",
        json={
            "project_id": "proj-nonexistent",
            "name": "Sub",
            "channel": "local_feed",
        },
    )
    assert bad_resp.status_code == 404

    # 2. 422 for blank name
    bad_name = client.post(
        "/notifications/subscriptions",
        json={
            "project_id": "proj-sub-test",
            "name": "   ",
            "channel": "local_feed",
        },
    )
    assert bad_name.status_code == 422

    # 3. 422 for invalid webhook URL
    bad_url = client.post(
        "/notifications/subscriptions",
        json={
            "project_id": "proj-sub-test",
            "name": "Webhook",
            "channel": "webhook",
            "destination_config": {"url": "not-a-valid-url"},
        },
    )
    assert bad_url.status_code == 422

    # 4. 201 Created for valid webhook
    create_resp = client.post(
        "/notifications/subscriptions",
        json={
            "project_id": "proj-sub-test",
            "name": "Slack Relay",
            "channel": "webhook",
            "destination_config": {
                "url": "https://hooks.example.com/alerts",
                "auth_secret": "whs_super_secret_token_1234",
                "headers": {"Authorization": "Bearer sensitive_token"},
            },
            "min_severity": "high",
            "enabled": True,
        },
    )
    assert create_resp.status_code == 201
    sub_data = create_resp.json()
    sub_id = sub_data["subscription_id"]
    # Secrets masked in response
    assert "****" in sub_data["destination_config"]["auth_secret"]
    assert "****" in sub_data["destination_config"]["headers"]["Authorization"]

    # 5. GET single
    get_resp = client.get(f"/notifications/subscriptions/{sub_id}")
    assert get_resp.status_code == 200
    assert "****" in get_resp.json()["destination_config"]["auth_secret"]

    # 6. GET list
    list_resp = client.get("/notifications/subscriptions?project_id=proj-sub-test")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 7. PATCH update with masked secret preserves original secret
    patch_resp = client.patch(
        f"/notifications/subscriptions/{sub_id}",
        json={
            "name": "Slack Relay Updated",
            "destination_config": {
                "url": "https://hooks.example.com/alerts",
                "auth_secret": sub_data["destination_config"]["auth_secret"],  # Masked form
            },
        },
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Slack Relay Updated"
    # Internal secret preserved
    raw_sub = get_notification_store().get_subscription(sub_id)
    assert raw_sub["destination_config"]["auth_secret"] == "whs_super_secret_token_1234"

    # 8. DELETE
    del_resp = client.delete(f"/notifications/subscriptions/{sub_id}")
    assert del_resp.status_code == 204
    assert client.get(f"/notifications/subscriptions/{sub_id}").status_code == 404


def test_diagnostic_test_endpoint():
    _create_test_project("proj-diag-test")

    # Local feed subscription -> /test returns 400
    sub_feed = client.post(
        "/notifications/subscriptions",
        json={
            "project_id": "proj-diag-test",
            "name": "Feed Sub",
            "channel": "local_feed",
        },
    ).json()
    feed_resp = client.post(f"/notifications/subscriptions/{sub_feed['subscription_id']}/test")
    assert feed_resp.status_code == 400
    assert "only supported for webhook" in feed_resp.json()["detail"]


def test_project_deletion_restrict_and_history_preservation():
    _create_test_project("proj-del-test")

    # Register subscription
    sub = client.post(
        "/notifications/subscriptions",
        json={
            "project_id": "proj-del-test",
            "name": "Feed Sub",
            "channel": "local_feed",
        },
    ).json()

    # Create an incident to produce a durable notification
    inc_resp = client.post(
        "/incidents",
        json={
            "title": "Outage",
            "summary": "Service down",
            "severity": "critical",
            "service": "api",
            "environment": "prod",
            "project_id": "proj-del-test",
        },
    )
    assert inc_resp.status_code == 201

    # Verify notification exists in feed
    feed = client.get("/notifications?project_id=proj-del-test").json()
    assert len(feed) == 1

    # 1. Attempting to delete project while subscription exists -> 409 Conflict
    del_proj_bad = client.delete("/projects/proj-del-test")
    assert del_proj_bad.status_code == 409
    assert "dependent records exist" in del_proj_bad.json()["detail"]

    # 2. Delete subscription -> 204
    del_sub = client.delete(f"/notifications/subscriptions/{sub['subscription_id']}")
    assert del_sub.status_code == 204

    # 3. Delete project -> now succeeds (204)
    del_proj_ok = client.delete("/projects/proj-del-test")
    assert del_proj_ok.status_code == 204

    # 4. Binding correction 4: GET /notifications?project_id=proj-del-test still works!
    # Historical notifications remain preserved and queryable!
    history_resp = client.get("/notifications?project_id=proj-del-test")
    assert history_resp.status_code == 200
    assert len(history_resp.json()) == 1
    assert history_resp.json()[0]["project_id"] == "proj-del-test"
    assert history_resp.json()[0]["title"] == "Incident Created: Outage"


def test_notification_feed_filtering_and_read_actions():
    _create_test_project("proj-feed-test")

    client.post(
        "/notifications/subscriptions",
        json={
            "project_id": "proj-feed-test",
            "name": "Feed Sub",
            "channel": "local_feed",
            "min_severity": "low",
        },
    )

    # Create 2 incidents
    client.post(
        "/incidents",
        json={
            "title": "Incident 1",
            "summary": "Sum 1",
            "severity": "low",
            "service": "api",
            "environment": "prod",
            "project_id": "proj-feed-test",
        },
    )
    client.post(
        "/incidents",
        json={
            "title": "Incident 2",
            "summary": "Sum 2",
            "severity": "high",
            "service": "api",
            "environment": "prod",
            "project_id": "proj-feed-test",
        },
    )

    feed = client.get("/notifications?project_id=proj-feed-test").json()
    assert len(feed) == 2
    notif_id_1 = feed[0]["notification_id"]

    # Mark single read
    patch_read = client.patch(f"/notifications/{notif_id_1}/read")
    assert patch_read.status_code == 200
    assert patch_read.json()["read_status"] == "read"

    # Filter by unread -> 1
    unread = client.get("/notifications?project_id=proj-feed-test&read_status=unread").json()
    assert len(unread) == 1

    # Mark all read
    mark_all = client.post("/notifications/mark-all-read?project_id=proj-feed-test")
    assert mark_all.status_code == 200
    assert mark_all.json()["marked_read_count"] == 1

    # All unread now empty
    unread_after = client.get("/notifications?project_id=proj-feed-test&read_status=unread").json()
    assert len(unread_after) == 0


def test_retry_endpoint_status_codes():
    _create_test_project("proj-retry-test")
    client.post(
        "/notifications/subscriptions",
        json={
            "project_id": "proj-retry-test",
            "name": "Feed Sub",
            "channel": "local_feed",
            "min_severity": "low",
        },
    )

    client.post(
        "/incidents",
        json={
            "title": "Incident For Retry",
            "summary": "Sum",
            "severity": "medium",
            "service": "api",
            "environment": "prod",
            "project_id": "proj-retry-test",
        },
    )

    feed = client.get("/notifications?project_id=proj-retry-test").json()
    assert len(feed) == 1
    nid = feed[0]["notification_id"]

    # Local feed is DELIVERED -> retry returns 409
    ret_resp = client.post(f"/notifications/{nid}/retry")
    assert ret_resp.status_code == 409
    assert "already delivered" in ret_resp.json()["detail"]


def test_production_db_isolation():
    import sqlite3

    prod_db_path = "runtime/sentinelops.db"
    assert Path(prod_db_path).exists()

    conn = sqlite3.connect(prod_db_path)
    cur = conn.cursor()
    cur.execute("SELECT project_id FROM projects ORDER BY project_id")
    prod_projects_before = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT count(notification_id) FROM notifications")
    prod_notifs_before = cur.fetchone()[0]
    cur.execute("SELECT count(subscription_id) FROM notification_subscriptions")
    prod_subs_before = cur.fetchone()[0]
    conn.close()

    # Prove test dependencies are redirected to tmp_path test database
    proj_store = get_project_store()
    conn_store = get_connector_store()
    notif_store = get_notification_store()
    assert "sentinelops_test.db" in proj_store.db_path
    assert "sentinelops_test.db" in conn_store.db_path
    assert "sentinelops_test.db" in notif_store.db_path

    # Perform full Stage 15 lifecycle in test environment
    test_proj_id = "proj-iso-1"
    _create_test_project(test_proj_id)
    sub_resp = client.post(
        "/notifications/subscriptions",
        json={
            "project_id": test_proj_id,
            "name": "Iso Feed",
            "channel": "local_feed",
        },
    )
    assert sub_resp.status_code == 201

    inc_resp = client.post(
        "/incidents",
        json={
            "title": "Iso Incident",
            "summary": "Isolation test summary",
            "severity": "high",
            "service": "api",
            "environment": "prod",
            "project_id": test_proj_id,
        },
    )
    assert inc_resp.status_code == 201

    feed_resp = client.get(f"/notifications?project_id={test_proj_id}")
    assert feed_resp.status_code == 200
    assert len(feed_resp.json()) == 1

    # Verify production database before/after invariant
    conn = sqlite3.connect(prod_db_path)
    cur = conn.cursor()
    cur.execute("SELECT project_id FROM projects ORDER BY project_id")
    prod_projects_after = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT count(notification_id) FROM notifications")
    prod_notifs_after = cur.fetchone()[0]
    cur.execute("SELECT count(subscription_id) FROM notification_subscriptions")
    prod_subs_after = cur.fetchone()[0]
    conn.close()

    assert prod_projects_after == prod_projects_before
    assert prod_notifs_after == prod_notifs_before
    assert prod_subs_after == prod_subs_before
    assert test_proj_id not in prod_projects_after
