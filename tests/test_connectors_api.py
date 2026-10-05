"""API integration tests for SentinelOps Connectors subsystem.

Verifies:
- Production DB isolation (never touches runtime/sentinelops.db)
- Shared project and connector SQLite database
- Full connector CRUD endpoints and 404/409/422/401 status semantics
- Foreign key ON DELETE RESTRICT on projects (409 Conflict)
- Webhook ingestion, authentication, Option B deduplication
- Project isolation and incident creation with explicit project_id
- Backward compatibility of direct POST /watcher/events
"""

from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.agents.dependencies import get_investigation_repository
from app.common.config import config
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
from app.projects.dependencies import (
    close_project_store,
    get_project_store,
    reset_project_state,
    set_custom_project_db_path,
)
from app.telemetry.dependencies import get_evidence_repository
from app.watcher.dependencies import reset_watcher_state

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_test_environment(tmp_path: Path) -> Generator[None, None, None]:
    """Ensure complete test isolation across ProjectStore, ConnectorStore, and Watcher."""
    test_db = str(tmp_path / "sentinelops_test.db")

    # Set both project and connector store to the SAME temporary database file
    set_custom_project_db_path(test_db)
    set_custom_connector_db_path(test_db)
    set_custom_incident_db_path(test_db)

    app.dependency_overrides.clear()
    reset_project_state()
    reset_connector_state(db_path=test_db)
    reset_incident_state(db_path=test_db)
    reset_knowledge_state()
    get_investigation_repository().clear()
    get_evidence_repository().clear()
    reset_watcher_state()

    # Safety check: confirm we are not touching production DB
    proj_store = get_project_store()
    conn_store = get_connector_store()
    assert "sentinelops_test.db" in proj_store.db_path
    assert "sentinelops_test.db" in conn_store.db_path
    assert not proj_store.db_path.endswith("runtime/sentinelops.db")

    yield

    close_incident_repository()
    close_connector_store()
    close_project_store()
    set_custom_incident_db_path(None)
    set_custom_project_db_path(None)
    set_custom_connector_db_path(None)


def _register_project(project_id: str, name: str, tmp_path: Path) -> dict:
    workspace = tmp_path / project_id
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


def test_connector_create_unknown_project_returns_404() -> None:
    resp = client.post(
        "/connectors",
        json={
            "connector_id": "conn-404",
            "project_id": "non-existent-proj",
            "name": "Orphan Connector",
            "connector_type": "webhook",
            "config": {},
        },
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_connector_crud_api_lifecycle(tmp_path: Path) -> None:
    _register_project("proj-crud", "CRUD Project", tmp_path)

    # 1. Create Webhook connector
    create_resp = client.post(
        "/connectors",
        json={
            "connector_id": "conn-test-1",
            "project_id": "proj-crud",
            "name": "Primary Webhook",
            "connector_type": "webhook",
            "config": {
                "auth_secret": "my-secret-key-12345",
                "service": "checkout-svc",
            },
        },
    )
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["connector_id"] == "conn-test-1"
    assert created_data["config"]["auth_secret"] != "my-secret-key-12345"
    assert "****" in created_data["config"]["auth_secret"]

    # 2. Get Connector
    get_resp = client.get("/connectors/conn-test-1")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Primary Webhook"
    assert get_resp.json()["health"]["operational_status"] == "healthy"

    # 3. List Connectors
    list_resp = client.get("/connectors?project_id=proj-crud")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # 4. Update Connector (preserving secret)
    masked_sec = created_data["config"]["auth_secret"]
    update_resp = client.put(
        "/connectors/conn-test-1",
        json={
            "name": "Primary Webhook Renamed",
            "config": {
                "auth_secret": masked_sec,
                "service": "checkout-svc-v2",
            },
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Primary Webhook Renamed"

    # 5. Delete Connector
    del_resp = client.delete("/connectors/conn-test-1")
    assert del_resp.status_code == 204

    # 6. Verify 404 after deletion
    assert client.get("/connectors/conn-test-1").status_code == 404


def test_project_deletion_rejected_with_409_when_connectors_exist(tmp_path: Path) -> None:
    _register_project("proj-with-conn", "Protected Project", tmp_path)

    # Add connector
    client.post(
        "/connectors",
        json={
            "connector_id": "conn-protect",
            "project_id": "proj-with-conn",
            "name": "Bound Connector",
            "connector_type": "webhook",
            "config": {},
        },
    )

    # Attempt to delete project -> 409 Conflict
    del_proj = client.delete("/projects/proj-with-conn")
    assert del_proj.status_code == 409
    assert "dependent records exist" in del_proj.json()["detail"].lower()

    # Delete connector first
    assert client.delete("/connectors/conn-protect").status_code == 204

    # Now project deletion succeeds -> 204
    del_proj_ok = client.delete("/projects/proj-with-conn")
    assert del_proj_ok.status_code == 204


def test_webhook_ingest_rejected_while_disabled(tmp_path: Path) -> None:
    _register_project("proj-disabled", "Disabled Project", tmp_path)

    client.post(
        "/connectors",
        json={
            "connector_id": "conn-dis",
            "project_id": "proj-disabled",
            "name": "Disabled Connector",
            "connector_type": "webhook",
            "status": "disabled",
            "config": {},
        },
    )

    resp = client.post(
        "/connectors/conn-dis/ingest",
        json={"message": "Should fail"},
    )
    assert resp.status_code == 409
    assert "disabled" in resp.json()["detail"].lower()


def test_wrong_connector_operation_returns_400(tmp_path: Path) -> None:
    _register_project("proj-ops", "Ops Project", tmp_path)

    # Create webhook connector
    client.post(
        "/connectors",
        json={
            "connector_id": "conn-wh",
            "project_id": "proj-ops",
            "name": "WH",
            "connector_type": "webhook",
            "config": {},
        },
    )

    # Create http_poller connector
    client.post(
        "/connectors",
        json={
            "connector_id": "conn-poll",
            "project_id": "proj-ops",
            "name": "Poll",
            "connector_type": "http_poller",
            "config": {"url": "http://127.0.0.1:8080/health"},
        },
    )

    # /collect on webhook must return 400
    collect_resp = client.post("/connectors/conn-wh/collect")
    assert collect_resp.status_code == 400
    assert "webhook connector" in collect_resp.json()["detail"].lower()

    # /ingest on http_poller must return 400
    ingest_resp = client.post("/connectors/conn-poll/ingest", json={"message": "fail"})
    assert ingest_resp.status_code == 400
    assert "unsupported" in ingest_resp.json()["detail"].lower()


def test_webhook_bad_auth_returns_401_without_degrading_health(tmp_path: Path) -> None:
    _register_project("proj-auth", "Auth Project", tmp_path)

    secret = "hmac-secret-123456"
    client.post(
        "/connectors",
        json={
            "connector_id": "conn-secured",
            "project_id": "proj-auth",
            "name": "Secured Webhook",
            "connector_type": "webhook",
            "config": {
                "auth_secret": secret,
                "signature_header": "X-Hub-Signature-256",
            },
        },
    )

    # Send with bad signature
    resp = client.post(
        "/connectors/conn-secured/ingest",
        headers={"X-Hub-Signature-256": "sha256=invalid"},
        json={"message": "Test"},
    )
    assert resp.status_code == 401

    # Verify health remains healthy
    health_resp = client.get("/connectors/conn-secured")
    assert health_resp.json()["health"]["operational_status"] == "healthy"
    assert health_resp.json()["health"]["consecutive_operational_errors"] == 0


def test_webhook_duplicate_suppression_and_two_project_isolation(tmp_path: Path) -> None:
    _register_project("stage14-alpha", "Alpha Project", tmp_path)
    _register_project("stage14-beta", "Beta Project", tmp_path)

    # Create Webhook connector for Beta
    client.post(
        "/connectors",
        json={
            "connector_id": "conn-beta-wh",
            "project_id": "stage14-beta",
            "name": "Beta Webhook",
            "connector_type": "webhook",
            "config": {"service": "beta-service"},
        },
    )

    # Ingest error event for Beta with stable external_event_id
    payload = {
        "external_event_id": "beta-evt-001",
        "level": "ERROR",
        "signal_type": "log",
        "event_type": "deployment.failure",
        "message": "Deployment container crash in Beta",
    }

    # First delivery: ingested
    resp1 = client.post("/connectors/conn-beta-wh/ingest", json=payload)
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "ingested"
    assert resp1.json()["external_event_id"] == "beta-evt-001"

    # Second delivery: suppressed duplicate
    resp2 = client.post("/connectors/conn-beta-wh/ingest", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate_suppressed"
    assert resp2.json()["external_event_id"] == "beta-evt-001"

    # Verify Stage 11/12/13 Incident creation for Beta
    incidents = client.get("/incidents").json()
    beta_incidents = [inc for inc in incidents if inc["project_id"] == "stage14-beta"]
    alpha_incidents = [inc for inc in incidents if inc["project_id"] == "stage14-alpha"]

    assert len(beta_incidents) >= 1
    # Isolation Invariant: Alpha receives zero incidents/evidence from Beta
    assert len(alpha_incidents) == 0


def test_test_endpoint_does_not_mutate_health(tmp_path: Path) -> None:
    _register_project("proj-test-ep", "Test Endpoint Project", tmp_path)

    client.post(
        "/connectors",
        json={
            "connector_id": "conn-diag",
            "project_id": "proj-test-ep",
            "name": "Diag Webhook",
            "connector_type": "webhook",
            "config": {"auth_secret": "test-sec"},
        },
    )

    test_resp = client.post("/connectors/conn-diag/test")
    assert test_resp.status_code == 200
    assert test_resp.json()["status"] == "active"

    # Health remains unchanged
    health = client.get("/connectors/conn-diag").json()["health"]
    assert health["last_poll_at"] is None
    assert health["consecutive_operational_errors"] == 0


def test_direct_watcher_events_endpoint_remains_backward_compatible() -> None:
    resp = client.post(
        "/watcher/events",
        json={
            "project_id": "legacy-proj",
            "service": "order-api",
            "signal_type": "log",
            "level": "INFO",
            "event_type": "order.created",
            "message": "Order 123 placed successfully",
        },
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"
    assert resp.json()["ingested_count"] == 1


def test_typed_config_validation(tmp_path: Path) -> None:
    _register_project("proj-valid", "Valid Project", tmp_path)

    # Missing URL for http_poller
    r1 = client.post(
        "/connectors",
        json={
            "project_id": "proj-valid",
            "name": "Bad Poller",
            "connector_type": "http_poller",
            "config": {},
        },
    )
    assert r1.status_code == 422

    # Invalid URL scheme
    r2 = client.post(
        "/connectors",
        json={
            "project_id": "proj-valid",
            "name": "FTP Poller",
            "connector_type": "http_poller",
            "config": {"url": "ftp://bad.host/health"},
        },
    )
    assert r2.status_code == 422

    # Poll interval below 5 seconds
    r3 = client.post(
        "/connectors",
        json={
            "project_id": "proj-valid",
            "name": "Fast Poller",
            "connector_type": "http_poller",
            "config": {"url": "http://127.0.0.1:8080/health", "poll_interval_seconds": 2},
        },
    )
    assert r3.status_code == 422


def test_malformed_webhook_rejected_with_422_without_degrading_health(tmp_path: Path) -> None:
    _register_project("proj-malformed", "Malformed Project", tmp_path)

    client.post(
        "/connectors",
        json={
            "connector_id": "conn-mal",
            "project_id": "proj-malformed",
            "name": "Mal Webhook",
            "connector_type": "webhook",
            "config": {},
        },
    )

    # Send non-JSON body
    resp = client.post(
        "/connectors/conn-mal/ingest",
        content="NOT_VALID_JSON{{{",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422

    # Health remains healthy
    health = client.get("/connectors/conn-mal").json()["health"]
    assert health["operational_status"] == "healthy"
    assert health["consecutive_operational_errors"] == 0


def test_connector_project_id_overrides_client_supplied_project_id(tmp_path: Path) -> None:
    _register_project("proj-real-owner", "Real Owner Project", tmp_path)

    client.post(
        "/connectors",
        json={
            "connector_id": "conn-override",
            "project_id": "proj-real-owner",
            "name": "Override Webhook",
            "connector_type": "webhook",
            "config": {},
        },
    )

    # Client tries to spoof another project
    resp = client.post(
        "/connectors/conn-override/ingest",
        json={
            "project_id": "attacker-spoofed-project",
            "level": "ERROR",
            "signal_type": "log",
            "message": "Critical crash",
        },
    )
    assert resp.status_code == 200

    # Incident created must have connector's project_id, NOT attacker's
    incidents = client.get("/incidents").json()
    owned_incidents = [i for i in incidents if i["project_id"] == "proj-real-owner"]
    spoofed_incidents = [i for i in incidents if i["project_id"] == "attacker-spoofed-project"]

    assert len(owned_incidents) >= 1
    assert len(spoofed_incidents) == 0


def test_get_connector_runtime_returns_concrete_instances() -> None:
    from app.connectors.dependencies import (
        get_connector_runtime,
        get_connector_service,
        get_connector_store,
    )
    from app.connectors.poller import ConnectorPollerRuntime
    from app.connectors.service import ConnectorService
    from app.connectors.store import SqliteConnectorStore
    from app.watcher.service import WatcherService

    store = get_connector_store()
    assert isinstance(store, SqliteConnectorStore)
    assert type(store).__name__ != "Depends"

    runtime = get_connector_runtime()
    assert isinstance(runtime, ConnectorPollerRuntime)
    assert isinstance(runtime._store, SqliteConnectorStore)
    assert type(runtime._store).__name__ != "Depends"
    assert isinstance(runtime._watcher_service, WatcherService)
    assert type(runtime._watcher_service).__name__ != "Depends"

    service = get_connector_service()
    assert isinstance(service, ConnectorService)
    assert service._runtime is runtime


@pytest.mark.asyncio
async def test_application_lifespan_starts_and_stops_cleanly() -> None:
    from app.connectors.dependencies import get_connector_runtime

    # Exercise the application lifespan context directly
    async with app.router.lifespan_context(app):
        runtime = get_connector_runtime()
        assert runtime.is_running is True

    # After lifespan shutdown, runtime is stopped
    assert runtime.is_running is False


@pytest.mark.asyncio
async def test_async_api_http_poller_lifecycle_with_running_loop(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, patch
    from httpx import ASGITransport, AsyncClient
    from app.connectors.dependencies import get_connector_runtime

    _register_project("proj-async-poller", "Async Poller Project", tmp_path)

    async with app.router.lifespan_context(app):
        runtime = get_connector_runtime()
        assert runtime.is_running is True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. Create enabled http_poller via real async API: must succeed with 201 without RuntimeError
            create_res = await ac.post(
                "/connectors",
                json={
                    "connector_id": "conn-live-poller",
                    "project_id": "proj-async-poller",
                    "name": "Live Poller",
                    "connector_type": "http_poller",
                    "config": {"url": "http://127.0.0.1:8080/health", "poll_interval_seconds": 15},
                    "status": "active",
                },
            )
            assert create_res.status_code == 201
            assert "conn-live-poller" in runtime._tasks
            assert not runtime._tasks["conn-live-poller"].done()

            # 2. Disable endpoint stops polling
            dis_res = await ac.put(
                "/connectors/conn-live-poller",
                json={"status": "disabled"},
            )
            assert dis_res.status_code == 200
            assert "conn-live-poller" not in runtime._tasks

            # 3. Enable endpoint restarts polling
            en_res = await ac.put(
                "/connectors/conn-live-poller",
                json={"status": "active"},
            )
            assert en_res.status_code == 200
            assert "conn-live-poller" in runtime._tasks

            # 4. Update requiring restart runs on event loop
            up_res = await ac.put(
                "/connectors/conn-live-poller",
                json={"config": {"url": "http://127.0.0.1:8080/health_v2", "poll_interval_seconds": 20}},
            )
            assert up_res.status_code == 200
            assert "conn-live-poller" in runtime._tasks

            # 5. Manual collect executes through async path
            with patch.object(runtime, "execute_single_poll", new_callable=AsyncMock) as mock_poll:
                mock_poll.return_value = {"status": "success", "status_code": 200}
                col_res = await ac.post("/connectors/conn-live-poller/collect")
                assert col_res.status_code == 200
                assert col_res.json()["status"] == "success"

            # 6. Delete cleanly stops active task
            del_res = await ac.delete("/connectors/conn-live-poller")
            assert del_res.status_code == 204
            assert "conn-live-poller" not in runtime._tasks



