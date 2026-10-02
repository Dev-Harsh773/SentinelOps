"""Unit tests for NotificationDeliveryRuntime webhook dispatch, backoff, and recovery."""

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import pytest
import httpx

from app.incidents.models import Severity
from app.notifications.delivery import NotificationDeliveryRuntime
from app.notifications.models import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationType,
)
from app.notifications.store import SqliteNotificationStore


@pytest.fixture
def delivery_env(tmp_path: Path):
    db_file = str(tmp_path / "sentinelops_test.db")
    store = SqliteNotificationStore(db_path=db_file)
    runtime = NotificationDeliveryRuntime(store=store, poll_interval_seconds=0.05, base_backoff_seconds=0.05)
    yield runtime, store
    store.close()


@pytest.mark.asyncio
async def test_webhook_delivery_success(delivery_env):
    runtime, store = delivery_env

    received_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        received_requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(mock_handler)
    runtime._http_client = httpx.AsyncClient(transport=transport)

    now = datetime.now(timezone.utc)
    notif = Notification(
        notification_id="notif-test-1",
        project_id="proj-alpha",
        incident_id="inc-1",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="High Error Rate",
        message="500 responses detected",
        payload={"service": "auth", "environment": "prod"},
        delivery_config={
            "url": "https://hooks.example.com/alerts",
            "auth_secret": "my-secret-key",
            "headers": {"X-Custom-Env": "prod", "X-SentinelOps-Notification-Id": "spoofed-id"},
        },
        channel=NotificationChannel.WEBHOOK,
        recipient="https://hooks.example.com/<redacted>",
        delivery_status=DeliveryStatus.PENDING,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    store.create_notification(notif)

    # Claim and deliver
    claimed = store.claim_due_notifications(limit=1, now=now)
    assert len(claimed) == 1
    await runtime._deliver_webhook(claimed[0])

    updated = store.get_notification("notif-test-1")
    assert updated.delivery_status == DeliveryStatus.DELIVERED
    assert updated.delivered_at is not None
    assert updated.next_attempt_at is None
    assert updated.failure_reason is None

    # Verify request payload and HMAC
    assert len(received_requests) == 1
    req = received_requests[0]
    body = req.read()
    payload = json.loads(body.decode("utf-8"))
    assert payload["notification_id"] == "notif-test-1"
    assert payload["service"] == "auth"

    # Verify HMAC calculation
    expected_sig = hmac.new(b"my-secret-key", body, hashlib.sha256).hexdigest()
    assert req.headers["X-SentinelOps-Signature"] == f"sha256={expected_sig}"

    # Verify reserved headers cannot be overridden
    assert req.headers["X-SentinelOps-Notification-Id"] == "notif-test-1"
    assert req.headers["X-Custom-Env"] == "prod"


@pytest.mark.asyncio
async def test_retryable_status_codes_and_backoff(delivery_env):
    runtime, store = delivery_env

    for code in (408, 429, 500, 502, 503, 504):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(code, text=f"Error {code}")

        runtime._http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

        nid = f"notif-code-{code}"
        now = datetime.now(timezone.utc)
        notif = Notification(
            notification_id=nid,
            project_id="proj-alpha",
            notification_type=NotificationType.INCIDENT_CREATED,
            severity=Severity.HIGH,
            title="Error",
            message="Msg",
            payload={},
            delivery_config={"url": "https://hooks.example.com/alerts"},
            channel=NotificationChannel.WEBHOOK,
            recipient="https://hooks.example.com/<redacted>",
            delivery_status=DeliveryStatus.PENDING,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        store.create_notification(notif)

        claimed = store.claim_due_notifications(limit=1, now=now)
        assert len(claimed) == 1
        await runtime._deliver_webhook(claimed[0])

        updated = store.get_notification(nid)
        assert updated.delivery_status == DeliveryStatus.PENDING
        assert updated.attempt_count == 1
        assert updated.next_attempt_at is not None
        assert f"HTTP {code}" in updated.failure_reason


@pytest.mark.asyncio
async def test_terminal_status_codes(delivery_env):
    runtime, store = delivery_env

    for code in (400, 401, 403, 404, 422):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(code, text=f"Client Error {code}")

        runtime._http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

        nid = f"notif-term-{code}"
        now = datetime.now(timezone.utc)
        notif = Notification(
            notification_id=nid,
            project_id="proj-alpha",
            notification_type=NotificationType.INCIDENT_CREATED,
            severity=Severity.HIGH,
            title="Terminal Error",
            message="Msg",
            payload={},
            delivery_config={"url": "https://hooks.example.com/alerts"},
            channel=NotificationChannel.WEBHOOK,
            recipient="https://hooks.example.com/<redacted>",
            delivery_status=DeliveryStatus.PENDING,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        store.create_notification(notif)

        claimed = store.claim_due_notifications(limit=1, now=now)
        await runtime._deliver_webhook(claimed[0])

        updated = store.get_notification(nid)
        assert updated.delivery_status == DeliveryStatus.FAILED
        assert updated.attempt_count == 1
        assert updated.next_attempt_at is None
        assert f"HTTP {code}" in updated.failure_reason


@pytest.mark.asyncio
async def test_max_attempts_exhaustion(delivery_env):
    runtime, store = delivery_env

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Server Error")

    runtime._http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    now = datetime.now(timezone.utc)
    notif = Notification(
        notification_id="notif-exhaust",
        project_id="proj-alpha",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Exhaustion Test",
        message="Msg",
        payload={},
        delivery_config={"url": "https://hooks.example.com/alerts"},
        channel=NotificationChannel.WEBHOOK,
        recipient="https://hooks.example.com/<redacted>",
        delivery_status=DeliveryStatus.PENDING,
        attempt_count=2,  # Already attempted twice
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    store.create_notification(notif)

    # 3rd claim -> attempt_count becomes 3
    claimed = store.claim_due_notifications(limit=1, now=now)
    assert len(claimed) == 1
    assert claimed[0].attempt_count == 3

    await runtime._deliver_webhook(claimed[0])

    updated = store.get_notification("notif-exhaust")
    assert updated.delivery_status == DeliveryStatus.FAILED
    assert updated.attempt_count == 3
    assert updated.next_attempt_at is None


@pytest.mark.asyncio
async def test_diagnostic_ping(delivery_env):
    runtime, store = delivery_env

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-SentinelOps-Diagnostic"] == "true"
        return httpx.Response(200, json={"ack": True})

    runtime._http_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    res = await runtime.send_diagnostic_ping(
        url="https://hooks.example.com/alerts",
        auth_secret="test-secret",
        headers={"X-Test": "1"},
        timeout_seconds=5.0,
        subscription_enabled=True,
    )
    assert res.success is True
    assert res.status_code == 200
    assert res.error is None
    # Verifies zero side-effects in notifications table
    assert len(store.list_notifications()) == 0
