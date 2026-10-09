"""Stage 21 tests for Connector One-Time Webhook Secret API Contract & Masking."""

import pytest
from fastapi.testclient import TestClient

from app.common.config import AppConfig
from app.connectors.dependencies import reset_connector_state, set_custom_connector_db_path
from app.knowledge.dependencies import reset_knowledge_state
from app.main import create_app
from app.projects.dependencies import reset_project_state, set_custom_project_db_path
from app.watcher.dependencies import reset_watcher_state


@pytest.fixture
def client(tmp_path):
    db_file = str(tmp_path / "stage21_connectors.db")

    set_custom_project_db_path(db_file)
    set_custom_connector_db_path(db_file)
    reset_project_state()
    reset_connector_state()
    reset_knowledge_state()
    reset_watcher_state()

    # Pre-create a project
    app = create_app()
    with TestClient(app) as test_client:
        ws = tmp_path / "dummy_workspace"
        ws.mkdir()
        reg = test_client.post(
            "/projects",
            json={"name": "Payment Service", "workspace_path": str(ws)},
        )
        assert reg.status_code == 201
        yield test_client

    reset_connector_state()
    reset_project_state()
    reset_knowledge_state()
    reset_watcher_state()
    set_custom_project_db_path(None)
    set_custom_connector_db_path(None)


def test_webhook_connector_returns_raw_secret_on_creation_only(client):
    """POST /connectors returns raw_auth_secret when generate_secret is True; subsequent GET returns masked secret."""
    create_payload = {
        "project_id": "payment-service",
        "name": "GitHub Webhook Ingress",
        "connector_type": "webhook",
        "generate_secret": True,
        "config": {
            "token_header": "X-Sentinel-Secret",
        },
    }

    # 1. POST /connectors
    resp = client.post("/connectors", json=create_payload)
    assert resp.status_code == 201
    created = resp.json()

    raw_secret = created.get("raw_auth_secret")
    assert raw_secret is not None
    assert raw_secret.startswith("sk-sec-")
    # Config auth_secret in creation body must be masked
    assert created["config"]["auth_secret"].startswith("sk-****")
    connector_id = created["connector_id"]

    # 2. Subsequent GET /connectors/{id} must NOT expose raw_auth_secret
    get_resp = client.get(f"/connectors/{connector_id}")
    assert get_resp.status_code == 200
    got = get_resp.json()
    assert got.get("raw_auth_secret") is None
    assert got["config"]["auth_secret"].startswith("sk-****")
    assert raw_secret not in got["config"]["auth_secret"]

    # 3. GET /connectors (list) must NOT expose raw_auth_secret
    list_resp = client.get("/connectors?project_id=payment-service")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0].get("raw_auth_secret") is None
    assert items[0]["config"]["auth_secret"].startswith("sk-****")


def test_webhook_custom_secret_creation_and_masking(client):
    """Providing explicit custom secret returns it once on creation, then masks."""
    custom_secret = "my-custom-super-secret-1234"
    create_payload = {
        "project_id": "payment-service",
        "name": "Custom Webhook",
        "connector_type": "webhook",
        "config": {
            "auth_secret": custom_secret,
            "token_header": "X-Sentinel-Secret",
        },
    }

    resp = client.post("/connectors", json=create_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["raw_auth_secret"] == custom_secret
    assert data["config"]["auth_secret"] != custom_secret

    conn_id = data["connector_id"]
    get_resp = client.get(f"/connectors/{conn_id}")
    assert get_resp.status_code == 200
    assert get_resp.json().get("raw_auth_secret") is None


def test_webhook_ingestion_with_raw_secret_succeeds_and_wrong_secret_fails(client):
    """Telemetry ingestion using the generated raw secret succeeds (HTTP 200), bad secret fails (HTTP 401)."""
    create_payload = {
        "project_id": "payment-service",
        "name": "Telemetry Ingress",
        "connector_type": "webhook",
        "generate_secret": True,
        "config": {
            "token_header": "X-Sentinel-Secret",
        },
    }
    resp = client.post("/connectors", json=create_payload)
    assert resp.status_code == 201
    created = resp.json()
    raw_secret = created["raw_auth_secret"]
    connector_id = created["connector_id"]

    # Ingestion with valid secret
    ingest_payload = {
        "event_type": "deploy.completed",
        "level": "INFO",
        "message": "Deployment v1.2 finished",
    }
    ingest_resp = client.post(
        f"/connectors/{connector_id}/ingest",
        json=ingest_payload,
        headers={"X-Sentinel-Secret": raw_secret},
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["status"] == "ingested"

    # Ingestion with invalid secret
    bad_resp = client.post(
        f"/connectors/{connector_id}/ingest",
        json=ingest_payload,
        headers={"X-Sentinel-Secret": "wrong-secret-token"},
    )
    assert bad_resp.status_code == 401


def test_http_poller_connector_does_not_expose_raw_auth_secret(client):
    """HTTP Poller connectors do not generate or expose raw_auth_secret."""
    poller_payload = {
        "project_id": "payment-service",
        "name": "Health Poller",
        "connector_type": "http_poller",
        "config": {
            "url": "http://127.0.0.1:8000/health",
            "poll_interval_seconds": 60,
        },
    }
    resp = client.post("/connectors", json=poller_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data.get("raw_auth_secret") is None


def test_unauthenticated_webhook_creation_preserves_legacy_semantics(client):
    """Legacy unauthenticated webhook creation does not generate secret and accepts unauthenticated posts."""
    # 1. Legacy creation: no generate_secret, no auth_secret
    legacy_payload = {
        "project_id": "payment-service",
        "name": "Legacy Unauthenticated Webhook",
        "connector_type": "webhook",
        "config": {},
    }
    resp = client.post("/connectors", json=legacy_payload)
    assert resp.status_code == 201
    created = resp.json()
    assert created.get("raw_auth_secret") is None
    assert created["config"].get("auth_secret") is None
    legacy_conn_id = created["connector_id"]

    # 2. Ingestion without any auth headers succeeds (HTTP 200)
    ingest_resp = client.post(
        f"/connectors/{legacy_conn_id}/ingest",
        json={"event_type": "legacy.event", "message": "unauthenticated success"},
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["status"] == "ingested"
