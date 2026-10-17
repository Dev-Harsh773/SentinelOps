"""Unit tests for the restricted validation ingress gateway."""

from unittest.mock import AsyncMock, patch
import httpx
import pytest
from starlette.testclient import TestClient
from tools.validation_gateway.gateway import create_gateway_app, MAX_BODY_BYTES


@pytest.fixture
def test_client():
    app = create_gateway_app(upstream_url="http://127.0.0.1:8000")
    return TestClient(app)


def test_allowed_path_and_method_proxies_upstream(test_client):
    """POST /connectors/{id}/ingest is permitted and forwards payload and auth header."""
    fake_response = httpx.Response(
        status_code=200,
        content=b'{"status":"accepted","received_at":"2026-10-10T00:00:00Z"}',
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "http://127.0.0.1:8000/connectors/conn-42/ingest"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = fake_response

        response = test_client.post(
            "/connectors/conn-42/ingest",
            json={"service": "chaos-app", "signal_type": "log", "message": "Test event"},
            headers={"X-Sentinel-Secret": "super-secret-token", "X-Request-ID": "req-999"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

        # Verify proxy called exact upstream endpoint with correct headers and payload
        mock_post.assert_awaited_once()
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "http://127.0.0.1:8000/connectors/conn-42/ingest"
        assert call_kwargs["headers"].get("x-sentinel-secret") == "super-secret-token"
        assert call_kwargs["headers"].get("x-request-id") == "req-999"


def test_disallowed_paths_rejected_with_404(test_client):
    """All non-ingest paths must return 404 and NEVER proxy upstream."""
    for path in ["/", "/projects", "/connectors", "/connectors/conn-42", "/api/v1/incidents", "/admin"]:
        res_get = test_client.get(path)
        assert res_get.status_code == 404, f"Path {path} GET should be 404"

        res_post = test_client.post(path, json={"data": 1})
        assert res_post.status_code == 404, f"Path {path} POST should be 404"


def test_disallowed_methods_on_ingest_path_rejected_with_405(test_client):
    """Methods other than POST on /connectors/{id}/ingest return 405."""
    for method in ["get", "put", "delete", "patch"]:
        res = getattr(test_client, method)("/connectors/conn-42/ingest")
        assert res.status_code == 405, f"Method {method.upper()} should be 405"


def test_body_size_limit_enforced_via_content_length(test_client):
    """Request with Content-Length exceeding 1MB returns 413."""
    headers = {"Content-Length": str(MAX_BODY_BYTES + 100), "Content-Type": "application/json"}
    # Send empty body but large header
    res = test_client.post("/connectors/conn-42/ingest", content=b"{}", headers=headers)
    assert res.status_code == 413
    assert "Payload exceeds 1 MB limit" in res.json()["detail"]


def test_body_size_limit_enforced_via_raw_payload(test_client):
    """Request with raw content exceeding 1MB returns 413."""
    large_payload = b"a" * (MAX_BODY_BYTES + 10)
    res = test_client.post("/connectors/conn-42/ingest", content=large_payload, headers={"Content-Type": "text/plain"})
    assert res.status_code == 413


def test_upstream_failure_returns_502(test_client):
    """Upstream network connection error returns 502 Bad Gateway."""
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
        res = test_client.post(
            "/connectors/conn-42/ingest",
            json={"service": "chaos"},
            headers={"X-Sentinel-Secret": "secret-123"},
        )
        assert res.status_code == 502
        assert "Upstream SentinelOps gateway error" in res.json()["detail"]


def test_secrets_not_logged(test_client, caplog):
    """Secret header values must never be logged."""
    fake_response = httpx.Response(
        status_code=200,
        content=b'{"status":"accepted"}',
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "http://127.0.0.1:8000/connectors/c/ingest"),
    )
    with patch("httpx.AsyncClient.post", return_value=fake_response):
        import logging
        with caplog.at_level(logging.DEBUG):
            test_client.post(
                "/connectors/conn-999/ingest",
                json={"event": "test"},
                headers={"X-Sentinel-Secret": "sensitive-token-xyz"},
            )
            assert "sensitive-token-xyz" not in caplog.text


def test_gateway_rejects_arbitrary_upstream():
    with pytest.raises(ValueError, match="upstream must"):
        create_gateway_app("https://example.com")


@pytest.mark.asyncio
async def test_stream_limit_stops_reading_without_content_length():
    app = create_gateway_app()
    consumed = []
    async def body():
        for index in range(5):
            consumed.append(index)
            yield b"a" * (MAX_BODY_BYTES // 2)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as upstream:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            response = await client.request("POST", "/connectors/test/ingest", content=body())
    assert response.status_code == 413
    assert len(consumed) == 3
    upstream.assert_not_called()
