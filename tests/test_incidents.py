"""Automated tests for Stage 1 Incident Management Core."""

import time
import pytest
from fastapi.testclient import TestClient

from app.incidents.dependencies import get_incident_repository
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_incident_storage():
    """Ensure in-memory repository is cleared before each test for total test isolation."""
    repo = get_incident_repository()
    # InMemoryIncidentRepository provides clear() exclusively for test isolation
    repo.clear()
    yield
    repo.clear()


def test_create_incident_success():
    """Verify creating an incident returns 201 with generated UUID, default OPEN status, and timestamps."""
    payload = {
        "title": "Checkout failure",
        "summary": "Checkout API is returning HTTP 500 on final payment step.",
        "severity": "high",
        "service": "checkout-service",
        "environment": "production",
    }
    response = client.post("/incidents", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert "id" in data and len(data["id"]) > 0
    assert data["title"] == "Checkout failure"
    assert data["summary"] == "Checkout API is returning HTTP 500 on final payment step."
    assert data["severity"] == "high"
    assert data["status"] == "open"
    assert data["service"] == "checkout-service"
    assert data["environment"] == "production"
    assert "created_at" in data
    assert "updated_at" in data
    assert data["created_at"] == data["updated_at"]


def test_create_incident_validation_rejects_empty_or_whitespace():
    """Verify creation rejects empty or whitespace-only fields with HTTP 422."""
    # Empty title
    res1 = client.post(
        "/incidents",
        json={
            "title": "   ",
            "summary": "Valid summary",
            "severity": "medium",
            "service": "auth-service",
            "environment": "production",
        },
    )
    assert res1.status_code == 422

    # Empty summary
    res2 = client.post(
        "/incidents",
        json={
            "title": "Valid title",
            "summary": "   ",
            "severity": "medium",
            "service": "auth-service",
            "environment": "production",
        },
    )
    assert res2.status_code == 422

    # Invalid severity
    res3 = client.post(
        "/incidents",
        json={
            "title": "Valid title",
            "summary": "Valid summary",
            "severity": "critical_extreme",
            "service": "auth-service",
            "environment": "production",
        },
    )
    assert res3.status_code == 422


def test_create_incident_trims_whitespace():
    """Verify fields with leading/trailing whitespace are cleanly trimmed."""
    res = client.post(
        "/incidents",
        json={
            "title": "  API Latency Spike  ",
            "summary": "  Latency exceeding 2000ms.  ",
            "severity": "low",
            "service": "  gateway  ",
            "environment": "  staging  ",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "API Latency Spike"
    assert data["summary"] == "Latency exceeding 2000ms."
    assert data["service"] == "gateway"
    assert data["environment"] == "staging"


def test_list_incidents():
    """Verify listing returns empty initially, and returns all created incidents."""
    initial_res = client.get("/incidents")
    assert initial_res.status_code == 200
    assert initial_res.json() == []

    client.post(
        "/incidents",
        json={
            "title": "Incident 1",
            "summary": "First summary",
            "severity": "low",
            "service": "service-a",
            "environment": "production",
        },
    )
    client.post(
        "/incidents",
        json={
            "title": "Incident 2",
            "summary": "Second summary",
            "severity": "critical",
            "service": "service-b",
            "environment": "staging",
        },
    )

    res = client.get("/incidents")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2
    titles = {item["title"] for item in items}
    assert titles == {"Incident 1", "Incident 2"}


def test_get_incident_by_id():
    """Verify retrieving an incident by ID returns 200 and matches created attributes."""
    create_res = client.post(
        "/incidents",
        json={
            "title": "Database connection pool exhausted",
            "summary": "Postgres pool reached 100% capacity.",
            "severity": "critical",
            "service": "order-service",
            "environment": "production",
        },
    )
    incident_id = create_res.json()["id"]

    get_res = client.get(f"/incidents/{incident_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == incident_id
    assert data["title"] == "Database connection pool exhausted"


def test_get_missing_incident_returns_404():
    """Verify retrieving a non-existent incident returns 404 with clear message."""
    res = client.get("/incidents/non-existent-uuid-12345")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_update_status_valid_lifecycle_transitions():
    """Verify valid status transitions: OPEN -> INVESTIGATING -> RESOLVED -> CLOSED."""
    create_res = client.post(
        "/incidents",
        json={
            "title": "Memory leak in worker",
            "summary": "Worker RAM consumption grows continuously.",
            "severity": "medium",
            "service": "worker",
            "environment": "production",
        },
    )
    incident_id = create_res.json()["id"]
    initial_updated_at = create_res.json()["updated_at"]

    # Small delay to ensure timestamp advancement without fragile sub-millisecond assumptions
    time.sleep(0.01)

    # 1. OPEN -> INVESTIGATING
    res1 = client.patch(f"/incidents/{incident_id}/status", json={"status": "investigating"})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "investigating"
    assert data1["updated_at"] > initial_updated_at

    time.sleep(0.01)

    # 2. INVESTIGATING -> RESOLVED
    res2 = client.patch(f"/incidents/{incident_id}/status", json={"status": "resolved"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "resolved"
    assert data2["updated_at"] > data1["updated_at"]

    time.sleep(0.01)

    # 3. RESOLVED -> CLOSED
    res3 = client.patch(f"/incidents/{incident_id}/status", json={"status": "closed"})
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["status"] == "closed"
    assert data3["updated_at"] > data2["updated_at"]


def test_update_status_direct_open_to_resolved():
    """Verify OPEN -> RESOLVED is a valid transition."""
    create_res = client.post(
        "/incidents",
        json={
            "title": "Quick transient glitch",
            "summary": "Resolved by automatic circuit breaker reset.",
            "severity": "low",
            "service": "payment",
            "environment": "production",
        },
    )
    incident_id = create_res.json()["id"]

    res = client.patch(f"/incidents/{incident_id}/status", json={"status": "resolved"})
    assert res.status_code == 200
    assert res.json()["status"] == "resolved"


def test_update_status_invalid_transitions_rejected():
    """Verify invalid transitions return HTTP 400 with a clear explanation."""
    create_res = client.post(
        "/incidents",
        json={
            "title": "Kafka partition lag",
            "summary": "Consumers lagged by 50,000 messages.",
            "severity": "high",
            "service": "stream-consumer",
            "environment": "production",
        },
    )
    incident_id = create_res.json()["id"]

    # Reject: OPEN -> CLOSED
    res_open_to_closed = client.patch(f"/incidents/{incident_id}/status", json={"status": "closed"})
    assert res_open_to_closed.status_code == 400
    assert "cannot transition" in res_open_to_closed.json()["detail"].lower()

    # Move to INVESTIGATING
    client.patch(f"/incidents/{incident_id}/status", json={"status": "investigating"})

    # Reject: INVESTIGATING -> CLOSED
    res_inv_to_closed = client.patch(f"/incidents/{incident_id}/status", json={"status": "closed"})
    assert res_inv_to_closed.status_code == 400
    assert "cannot transition" in res_inv_to_closed.json()["detail"].lower()

    # Move to RESOLVED
    client.patch(f"/incidents/{incident_id}/status", json={"status": "resolved"})

    # Reject: RESOLVED -> OPEN
    res_res_to_open = client.patch(f"/incidents/{incident_id}/status", json={"status": "open"})
    assert res_res_to_open.status_code == 400
    assert "cannot transition" in res_res_to_open.json()["detail"].lower()

    # Move to CLOSED
    client.patch(f"/incidents/{incident_id}/status", json={"status": "closed"})

    # Reject: CLOSED -> any other state (e.g. CLOSED -> OPEN, CLOSED -> INVESTIGATING, CLOSED -> RESOLVED)
    for target in ["open", "investigating", "resolved"]:
        res_closed_to_other = client.patch(f"/incidents/{incident_id}/status", json={"status": target})
        assert res_closed_to_other.status_code == 400
        assert "cannot transition" in res_closed_to_other.json()["detail"].lower()


def test_update_status_missing_incident_returns_404():
    """Verify status update on a non-existent incident returns 404."""
    res = client.patch("/incidents/non-existent-id/status", json={"status": "investigating"})
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()
