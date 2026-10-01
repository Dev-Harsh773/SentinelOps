"""Comprehensive test suite for Stage 10 — Sentinel Watcher Foundation."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient
import httpx

from app.main import app
from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.collectors.file_collector import JsonlFileCollector
from app.watcher.collectors.health_collector import HealthCheckCollector
from app.watcher.dependencies import (
    get_watcher_buffer,
    get_watcher_service,
    get_watcher_storage,
    reset_watcher_state,
)
from app.watcher.models import (
    CollectorHealth,
    CollectorStatus,
    CollectorType,
    SignalType,
    TelemetryEvent,
    WatcherStatus,
)
from app.watcher.schemas import TelemetryEventCreate
from app.watcher.service import WatcherService
from app.watcher.storage import SqliteTelemetryStore


@pytest.fixture(autouse=True)
def clean_watcher_environment():
    """Ensure test isolation by resetting Watcher dependencies before and after each test."""
    reset_watcher_state()
    yield
    reset_watcher_state()


# ---------------------------------------------------------------------------
# 1. Model & Schema Tests
# ---------------------------------------------------------------------------


def test_telemetry_event_immutability():
    """TelemetryEvent should be frozen and immutable."""
    event = TelemetryEvent(
        event_id=str(uuid.uuid4()),
        project_id="test-proj",
        service="test-svc",
        environment="test-env",
        signal_type=SignalType.LOG,
        source="test-src",
        timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        level="INFO",
        event_type="test_event",
        message="Test event message",
    )
    with pytest.raises(Exception):
        event.level = "ERROR"  # type: ignore


def test_telemetry_event_create_validation_requires_identity():
    """TelemetryEventCreate must strictly reject missing or whitespace-only project_id and service."""
    with pytest.raises(ValueError):
        TelemetryEventCreate(
            project_id="   ",
            service="valid-service",
            event_type="test",
            message="msg",
        )

    with pytest.raises(ValueError):
        TelemetryEventCreate(
            project_id="valid-project",
            service="",
            event_type="test",
            message="msg",
        )


def test_signal_type_enum_values():
    """Verify all required signal types are supported."""
    assert SignalType.LOG == "log"
    assert SignalType.HEALTH == "health"
    assert SignalType.METRIC == "metric"
    assert SignalType.TRACE == "trace"
    assert SignalType.DEPLOYMENT == "deployment"
    assert SignalType.CONTAINER == "container"
    assert SignalType.INFRASTRUCTURE == "infrastructure"
    assert SignalType.SECURITY == "security"
    assert SignalType.CUSTOM == "custom"


# ---------------------------------------------------------------------------
# 2. RollingTelemetryBuffer Tests
# ---------------------------------------------------------------------------


def test_buffer_fifo_eviction():
    """Verify strict O(1) FIFO eviction when capacity is exceeded."""
    buffer = RollingTelemetryBuffer(capacity=3)
    now = datetime.now(timezone.utc)

    events = [
        TelemetryEvent(
            event_id=f"evt-{i}",
            project_id="proj",
            service="svc",
            environment="dev",
            signal_type=SignalType.LOG,
            source="test",
            timestamp=now + timedelta(seconds=i),
            ingested_at=now + timedelta(seconds=i),
            level="INFO",
            event_type=f"event_{i}",
            message=f"msg {i}",
        )
        for i in range(5)
    ]

    for e in events:
        buffer.append(e)

    assert buffer.size() == 3
    recent = buffer.get_recent(limit=10)
    # Most recent first: evt-4, evt-3, evt-2
    assert [e.event_id for e in recent] == ["evt-4", "evt-3", "evt-2"]


def test_buffer_query_filtering():
    """Verify filtering by signal_type, level, service, and project_id."""
    buffer = RollingTelemetryBuffer(capacity=10)
    now = datetime.now(timezone.utc)

    e1 = TelemetryEvent(
        event_id="1",
        project_id="p1",
        service="orders",
        environment="prod",
        signal_type=SignalType.LOG,
        source="test",
        timestamp=now,
        ingested_at=now,
        level="ERROR",
        event_type="failed",
        message="m1",
    )
    e2 = TelemetryEvent(
        event_id="2",
        project_id="p1",
        service="orders",
        environment="prod",
        signal_type=SignalType.HEALTH,
        source="test",
        timestamp=now + timedelta(seconds=1),
        ingested_at=now + timedelta(seconds=1),
        level="INFO",
        event_type="ok",
        message="m2",
    )
    e3 = TelemetryEvent(
        event_id="3",
        project_id="p2",
        service="payments",
        environment="prod",
        signal_type=SignalType.LOG,
        source="test",
        timestamp=now + timedelta(seconds=2),
        ingested_at=now + timedelta(seconds=2),
        level="ERROR",
        event_type="failed",
        message="m3",
    )

    buffer.append(e1)
    buffer.append(e2)
    buffer.append(e3)

    # Filter by level
    errors = buffer.get_recent(level="ERROR")
    assert len(errors) == 2
    assert [e.event_id for e in errors] == ["3", "1"]

    # Filter by signal_type
    health = buffer.get_recent(signal_type=SignalType.HEALTH)
    assert len(health) == 1
    assert health[0].event_id == "2"

    # Filter by project_id
    p1_events = buffer.get_recent(project_id="p1")
    assert len(p1_events) == 2


# ---------------------------------------------------------------------------
# 3. SqliteTelemetryStore Tests
# ---------------------------------------------------------------------------


def test_sqlite_store_lifecycle_and_queries(tmp_path):
    """Verify SQLite persistence, batch insertion, and query ordering."""
    db_file = str(tmp_path / "test_watcher.db")
    store = SqliteTelemetryStore(db_path=db_file)
    now = datetime.now(timezone.utc)

    e1 = TelemetryEvent(
        event_id="evt-1",
        project_id="proj-a",
        service="svc-a",
        environment="dev",
        signal_type=SignalType.LOG,
        source="unit_test",
        timestamp=now,
        ingested_at=now,
        level="INFO",
        event_type="login",
        message="User logged in",
        request_id="req-123",
        metadata={"user_id": 42},
    )
    e2 = TelemetryEvent(
        event_id="evt-2",
        project_id="proj-a",
        service="svc-a",
        environment="dev",
        signal_type=SignalType.HEALTH,
        source="unit_test",
        timestamp=now + timedelta(seconds=2),
        ingested_at=now + timedelta(seconds=2),
        level="ERROR",
        event_type="health_check_failed",
        message="Probe timed out",
        status_code=504,
        metadata={"failure_type": "timeout"},
    )

    store.save_batch([e1, e2])
    assert store.count() == 2

    # Query single by ID
    retrieved = store.get_by_id("evt-1")
    assert retrieved is not None
    assert retrieved.request_id == "req-123"
    assert retrieved.metadata["user_id"] == 42

    # Query by request_id
    req_match = store.query(request_id="req-123")
    assert len(req_match) == 1
    assert req_match[0].event_id == "evt-1"

    # Query newest first
    all_events = store.query(limit=10)
    assert len(all_events) == 2
    assert all_events[0].event_id == "evt-2"

    store.close()


def test_sqlite_store_retention_pruning(tmp_path):
    """Verify both time-based and count-based retention pruning."""
    db_file = str(tmp_path / "retention_test.db")
    store = SqliteTelemetryStore(db_path=db_file)
    now = datetime.now(timezone.utc)

    # Insert 5 events, 2 of which are older than 24 hours
    old_time = now - timedelta(hours=48)
    events = [
        TelemetryEvent(
            event_id=f"old-{i}",
            project_id="p",
            service="s",
            environment="dev",
            signal_type=SignalType.LOG,
            source="test",
            timestamp=old_time + timedelta(seconds=i),
            ingested_at=now,
            level="INFO",
            event_type="old_event",
            message="old",
        )
        for i in range(2)
    ] + [
        TelemetryEvent(
            event_id=f"recent-{i}",
            project_id="p",
            service="s",
            environment="dev",
            signal_type=SignalType.LOG,
            source="test",
            timestamp=now + timedelta(seconds=i),
            ingested_at=now,
            level="INFO",
            event_type="recent_event",
            message="recent",
        )
        for i in range(3)
    ]

    store.save_batch(events)
    assert store.count() == 5

    # 1. Prune by retention hours (24h)
    pruned_time = store.prune(retention_hours=24)
    assert pruned_time == 2
    assert store.count() == 3

    # 2. Prune by max_events (cap at 2)
    pruned_count = store.prune(max_events=2)
    assert pruned_count == 1
    assert store.count() == 2

    store.close()


def test_sqlite_store_persistence_across_restart(tmp_path):
    """Verify that persisted telemetry survives store closure and process-level restart."""
    db_file = str(tmp_path / "restart_test.db")
    now = datetime.now(timezone.utc)

    # 1. First process / instance lifecycle
    store_1 = SqliteTelemetryStore(db_path=db_file)
    event_1 = TelemetryEvent(
        event_id="evt-restart-1",
        project_id="proj-restart",
        service="auth-service",
        environment="production",
        signal_type=SignalType.LOG,
        source="http_api",
        timestamp=now,
        ingested_at=now,
        level="WARNING",
        event_type="auth_failure",
        message="Invalid credentials attempt",
        request_id="req-auth-99",
        metadata={"ip": "192.168.1.1"},
    )
    event_2 = TelemetryEvent(
        event_id="evt-restart-2",
        project_id="proj-restart",
        service="auth-service",
        environment="production",
        signal_type=SignalType.HEALTH,
        source="health_check_collector",
        timestamp=now + timedelta(seconds=1),
        ingested_at=now + timedelta(seconds=1),
        level="INFO",
        event_type="health_check_passed",
        message="Auth service healthy",
        status_code=200,
    )
    store_1.save_batch([event_1, event_2])
    assert store_1.count() == 2

    # 2. Simulate process shutdown by closing store_1
    store_1.close()

    # 3. Simulate process restart by instantiating a fresh store pointing to the same DB file
    store_2 = SqliteTelemetryStore(db_path=db_file)
    try:
        # Confirm row count and integrity survived
        assert store_2.count() == 2

        # Confirm specific event retrieval and field preservation
        retrieved_1 = store_2.get_by_id("evt-restart-1")
        assert retrieved_1 is not None
        assert retrieved_1.event_id == "evt-restart-1"
        assert retrieved_1.project_id == "proj-restart"
        assert retrieved_1.service == "auth-service"
        assert retrieved_1.signal_type == SignalType.LOG
        assert retrieved_1.level == "WARNING"
        assert retrieved_1.request_id == "req-auth-99"
        assert retrieved_1.metadata["ip"] == "192.168.1.1"

        retrieved_2 = store_2.get_by_id("evt-restart-2")
        assert retrieved_2 is not None
        assert retrieved_2.signal_type == SignalType.HEALTH
        assert retrieved_2.status_code == 200

        # Confirm query operations work across restart
        auth_events = store_2.query(service="auth-service")
        assert len(auth_events) == 2
        assert [e.event_id for e in auth_events] == ["evt-restart-2", "evt-restart-1"]
    finally:
        store_2.close()


# ---------------------------------------------------------------------------

# 4. JsonlFileCollector Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jsonl_file_collector_startup_eof_and_tailing(tmp_path):
    """Verify collector seeks to EOF on startup and captures only new lines."""
    log_file = str(tmp_path / "app.jsonl")

    # Write historical lines before collector starts
    historical_event = {
        "timestamp": "2026-10-01T00:00:00Z",
        "level": "INFO",
        "service": "demo-app",
        "event": "historical_startup",
        "message": "Already happened",
    }
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(historical_event) + "\n")

    collector = JsonlFileCollector(
        log_path=log_file,
        project_id="proj-demo",
        service="demo-app",
        environment="dev",
        poll_interval_seconds=0.05,
    )

    emitted: list[TelemetryEvent] = []

    async def emit_cb(event: TelemetryEvent) -> None:
        emitted.append(event)

    await collector.start(emit_cb)

    # Confirm initial offset is at EOF (historical line not emitted)
    poll_result = await collector.poll_once()
    assert poll_result == 0
    assert len(emitted) == 0

    # Append new valid line
    new_event = {
        "timestamp": "2026-10-01T00:01:00Z",
        "level": "ERROR",
        "service": "demo-app",
        "event": "order_processing_failed",
        "message": "Payment timed out",
        "request_id": "req-999",
        "exception_type": "OrderProcessingError",
        "metadata": {"traceback": "Traceback info"},
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(new_event) + "\n")

    # Poll once to read the new line
    count = await collector.poll_once()
    assert count == 1
    assert len(emitted) == 1
    captured = emitted[0]
    assert captured.signal_type == SignalType.LOG
    assert captured.event_type == "order_processing_failed"
    assert captured.level == "ERROR"
    assert captured.request_id == "req-999"
    assert captured.exception_type == "OrderProcessingError"
    assert captured.project_id == "proj-demo"

    # Verify collector health
    health = collector.health()
    assert health.status == CollectorStatus.HEALTHY
    assert health.total_events_collected == 1
    assert health.error_count == 0

    await collector.stop()


@pytest.mark.asyncio
async def test_jsonl_collector_malformed_lines_and_truncation(tmp_path):
    """Verify collector skips malformed lines gracefully and handles file truncation."""
    log_file = str(tmp_path / "truncation_test.jsonl")

    collector = JsonlFileCollector(
        log_path=log_file,
        project_id="proj-demo",
        service="demo-app",
        environment="dev",
    )

    emitted: list[TelemetryEvent] = []

    async def emit_cb(event: TelemetryEvent) -> None:
        emitted.append(event)

    await collector.start(emit_cb)

    # Write a malformed JSON line followed by a valid line
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("{this is not valid json}\n")
        f.write(json.dumps({"level": "INFO", "event": "good_event", "message": "all good"}) + "\n")

    count = await collector.poll_once()
    assert count == 1
    assert len(emitted) == 1
    assert collector.health().error_count == 1  # Malformed line recorded

    # Now truncate file (simulate rotation or clearing)
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"level": "INFO", "event": "after_truncation", "message": "fresh"}) + "\n")

    count_after_truncate = await collector.poll_once()
    assert count_after_truncate == 1
    assert len(emitted) == 2
    assert emitted[1].event_type == "after_truncation"

    await collector.stop()


# ---------------------------------------------------------------------------
# 5. HealthCheckCollector Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_collector_success(monkeypatch):
    """Verify HealthCheckCollector successfully probing an endpoint."""
    collector = HealthCheckCollector(
        health_url="http://127.0.0.1:8001/health",
        project_id="demo-proj",
        service="demo-app",
        environment="dev",
    )

    emitted: list[TelemetryEvent] = []

    async def emit_cb(event: TelemetryEvent) -> None:
        emitted.append(event)

    # Mock httpx.AsyncClient.get returning 200
    class MockResponse:
        status_code = 200

    async def mock_get(self, url, **kwargs):
        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    await collector.start(emit_cb)
    event = await collector.probe_once()

    assert event is not None
    assert event.signal_type == SignalType.HEALTH
    assert event.level == "INFO"
    assert event.event_type == "health_check_passed"
    assert event.status_code == 200
    assert collector.health().status == CollectorStatus.HEALTHY

    await collector.stop()


@pytest.mark.asyncio
async def test_health_check_collector_failure_typing(monkeypatch):
    """Verify health probe failure preservation (connection_refused, timeout, http_status_failure)."""
    collector = HealthCheckCollector(
        health_url="http://127.0.0.1:8001/health",
        project_id="demo-proj",
        service="demo-app",
        environment="dev",
    )

    emitted: list[TelemetryEvent] = []

    async def emit_cb(event: TelemetryEvent) -> None:
        emitted.append(event)

    await collector.start(emit_cb)

    # 1. Connection Refused
    async def mock_connect_error(self, url, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_connect_error)
    e1 = await collector.probe_once()
    assert e1 is not None
    assert e1.level == "ERROR"
    assert e1.event_type == "health_check_failed"
    assert e1.metadata["failure_type"] == "connection_refused"
    assert collector.health().status == CollectorStatus.DEGRADED

    # 2. Timeout
    async def mock_timeout(self, url, **kwargs):
        raise httpx.TimeoutException("Read timeout")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_timeout)
    e2 = await collector.probe_once()
    assert e2 is not None
    assert e2.metadata["failure_type"] == "timeout"

    # 3. HTTP 500 status failure
    class Mock500Response:
        status_code = 500

    async def mock_500(self, url, **kwargs):
        return Mock500Response()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_500)
    e3 = await collector.probe_once()
    assert e3 is not None
    assert e3.metadata["failure_type"] == "http_status_failure"
    assert e3.status_code == 500

    await collector.stop()


# ---------------------------------------------------------------------------
# 6. HTTP API Routes Tests
# ---------------------------------------------------------------------------


def test_http_ingest_single_event_success(tmp_path):
    """Verify POST /watcher/events accepts valid telemetry and returns 202."""
    db_file = str(tmp_path / "api_test.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=100)
    service = WatcherService(buffer=buffer, storage=storage)

    app.dependency_overrides[get_watcher_service] = lambda: service
    client = TestClient(app)

    payload = {
        "project_id": "proj-alpha",
        "service": "billing-service",
        "signal_type": "log",
        "event_type": "invoice_generated",
        "message": "Invoice #1042 generated successfully",
        "level": "INFO",
        "request_id": "req-invoice-1042",
        "metadata": {"amount": 99.99},
    }

    resp = client.post("/watcher/events", json=payload)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["ingested_count"] == 1
    assert len(data["event_ids"]) == 1

    # Verify event reached buffer
    buffered = service.get_events(project_id="proj-alpha")
    assert len(buffered) == 1
    assert buffered[0].service == "billing-service"
    assert buffered[0].request_id == "req-invoice-1042"

    app.dependency_overrides.clear()
    storage.close()


def test_http_ingest_rejects_missing_identity():
    """Verify POST /watcher/events rejects payloads without explicit project_id or service with 422."""
    client = TestClient(app)

    # Missing project_id
    resp1 = client.post(
        "/watcher/events",
        json={
            "service": "auth-service",
            "signal_type": "log",
            "event_type": "login",
            "message": "User logged in",
        },
    )
    assert resp1.status_code == 422

    # Blank service
    resp2 = client.post(
        "/watcher/events",
        json={
            "project_id": "proj-1",
            "service": "   ",
            "signal_type": "log",
            "event_type": "login",
            "message": "User logged in",
        },
    )
    assert resp2.status_code == 422


def test_http_ingest_batch(tmp_path):
    """Verify batch ingestion of multiple events."""
    db_file = str(tmp_path / "batch_test.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=100)
    service = WatcherService(buffer=buffer, storage=storage)

    app.dependency_overrides[get_watcher_service] = lambda: service
    client = TestClient(app)

    payload = {
        "events": [
            {
                "project_id": "p1",
                "service": "s1",
                "signal_type": "metric",
                "event_type": "cpu_load",
                "message": "CPU load high",
                "level": "WARNING",
            },
            {
                "project_id": "p1",
                "service": "s2",
                "signal_type": "health",
                "event_type": "ping",
                "message": "Ping ok",
                "level": "INFO",
            },
        ]
    }

    resp = client.post("/watcher/events", json=payload)
    assert resp.status_code == 202
    data = resp.json()
    assert data["ingested_count"] == 2
    assert len(data["event_ids"]) == 2

    assert service.get_status().buffer["current_size"] == 2

    app.dependency_overrides.clear()
    storage.close()


def test_get_watcher_status_and_events(tmp_path):
    """Verify GET /watcher/status and GET /watcher/events endpoints."""
    db_file = str(tmp_path / "status_test.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=50)

    collector = HealthCheckCollector(
        health_url="http://mock/health",
        project_id="test-proj",
        service="test-svc",
        environment="test",
        name="test_health_collector",
    )
    service = WatcherService(buffer=buffer, storage=storage, collectors=[collector])

    app.dependency_overrides[get_watcher_service] = lambda: service
    client = TestClient(app)

    # 1. Status query
    status_resp = client.get("/watcher/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert "watcher_status" in status_data
    assert "buffer" in status_data
    assert "collectors" in status_data
    assert "test_health_collector" in status_data["collectors"]

    # 2. Ingest and query events
    client.post(
        "/watcher/events",
        json={
            "project_id": "test-proj",
            "service": "orders",
            "signal_type": "log",
            "event_type": "order_created",
            "message": "New order",
            "level": "INFO",
        },
    )

    events_resp = client.get("/watcher/events?limit=10")
    assert events_resp.status_code == 200
    events_data = events_resp.json()
    assert len(events_data) == 1
    assert events_data[0]["event_type"] == "order_created"
    assert events_data[0]["signal_type"] == "log"

    app.dependency_overrides.clear()
    storage.close()
