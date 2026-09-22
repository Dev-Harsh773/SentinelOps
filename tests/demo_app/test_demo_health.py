"""Tests for the demo application health endpoint."""


def test_demo_health_check(client):
    """Verify GET /health returns HTTP 200, service identifier, and X-Request-ID header."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "demo-app",
    }
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0
