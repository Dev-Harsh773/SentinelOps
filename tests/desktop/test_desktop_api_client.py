"""Unit tests for SentinelOpsClient HTTP operations and exception mapping."""

import json
import httpx
import pytest

from desktop.api.client import SentinelOpsClient
from desktop.api.exceptions import (
    BackendUnavailableError,
    ConflictError,
    NotFoundError,
    ServerError,
    ValidationError,
)


def test_client_health_check_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok", "service": "sentinelops"})

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://test-server", transport=transport)
    try:
        resp = client.get_health()
        assert resp["status"] == "ok"
        assert resp["service"] == "sentinelops"
    finally:
        client.close()


def test_client_list_projects():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/projects"
        return httpx.Response(
            200,
            json=[
                {
                    "project_id": "proj-alpha",
                    "name": "Alpha",
                    "workspace_path": "/var/repos/alpha",
                    "status": "ready",
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://test-server", transport=transport)
    try:
        projects = client.list_projects()
        assert len(projects) == 1
        assert projects[0].project_id == "proj-alpha"
        assert projects[0].name == "Alpha"
    finally:
        client.close()


def test_client_not_found_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Project 'missing' not found."})

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://test-server", transport=transport)
    try:
        with pytest.raises(NotFoundError) as exc:
            client.get_project("missing")
        assert exc.value.status_code == 404
        assert "not found" in exc.value.detail
    finally:
        client.close()


def test_client_conflict_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Project has active connectors."})

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://test-server", transport=transport)
    try:
        with pytest.raises(ConflictError) as exc:
            client._request("DELETE", "/projects/proj-1")
        assert exc.value.status_code == 409
        assert "active connectors" in exc.value.detail
    finally:
        client.close()


def test_client_validation_error_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "Cannot transition incident from OPEN to CLOSED."})

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://test-server", transport=transport)
    try:
        with pytest.raises(ValidationError) as exc:
            client.update_incident_status("inc-1", "closed")
        assert exc.value.status_code == 400
        assert "Cannot transition" in exc.value.detail
    finally:
        client.close()


def test_client_server_error_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "Database error"})

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://test-server", transport=transport)
    try:
        with pytest.raises(ServerError) as exc:
            client.list_incidents()
        assert exc.value.status_code == 500
    finally:
        client.close()


def test_client_backend_unavailable_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://test-server", transport=transport)
    try:
        with pytest.raises(BackendUnavailableError):
            client.get_health()
    finally:
        client.close()


def test_client_notification_operations():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/notifications":
            assert request.url.params["project_id"] == "proj-alpha"
            assert request.url.params["limit"] == "50"
            return httpx.Response(
                200,
                json=[
                    {
                        "notification_id": "notif-1",
                        "project_id": "proj-alpha",
                        "title": "Alert 1",
                        "message": "Message 1",
                        "read_status": "unread",
                        "delivery_status": "delivered",
                        "channel": "local_feed",
                        "recipient": "local",
                        "severity": "high",
                        "notification_type": "incident.created",
                        "attempt_count": 1,
                        "created_at": "2026-10-02T12:00:00Z",
                        "updated_at": "2026-10-02T12:00:00Z",
                    }
                ],
            )
        elif request.method == "PATCH" and request.url.path == "/notifications/notif-1/read":
            return httpx.Response(
                200,
                json={
                    "notification_id": "notif-1",
                    "project_id": "proj-alpha",
                    "title": "Alert 1",
                    "message": "Message 1",
                    "read_status": "read",
                    "delivery_status": "delivered",
                    "channel": "local_feed",
                    "recipient": "local",
                    "severity": "high",
                    "notification_type": "incident.created",
                    "attempt_count": 1,
                    "created_at": "2026-10-02T12:00:00Z",
                    "updated_at": "2026-10-02T12:00:00Z",
                },
            )
        elif request.method == "POST" and request.url.path == "/notifications/mark-all-read":
            assert request.url.params["project_id"] == "proj-alpha"
            return httpx.Response(200, json={"project_id": "proj-alpha", "marked_read_count": 5})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://test-server", transport=transport)
    try:
        notifs = client.list_notifications(project_id="proj-alpha", limit=50)
        assert len(notifs) == 1
        assert notifs[0].read_status == "unread"

        updated = client.mark_notification_read("notif-1")
        assert updated.read_status == "read"

        result = client.mark_all_notifications_read("proj-alpha")
        assert result["marked_read_count"] == 5
    finally:
        client.close()
