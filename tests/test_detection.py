"""Comprehensive test suite for Stage 11 — Detection Rules + Automatic Incident Creation."""

import asyncio
from datetime import datetime, timezone
import json
import uuid
import pytest

from app.common.config import config
from app.detection.dependencies import get_detection_engine, reset_detection_state
from app.detection.engine import DetectionEngine
from app.detection.models import DetectionAction
from app.detection.rules import AppErrorRule, HealthCheckFailureRule, Http5xxRule
from app.incidents.dependencies import get_incident_repository, get_incident_service
from app.incidents.models import IncidentStatus, Severity
from app.incidents.repository import InMemoryIncidentRepository
from app.incidents.service import IncidentService
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.models import EvidenceType
from app.telemetry.repository import InMemoryEvidenceRepository
from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.collectors.health_collector import HealthCheckCollector
from app.watcher.dependencies import reset_watcher_state
from app.watcher.models import SignalType, TelemetryEvent
from app.watcher.service import WatcherService
from app.watcher.storage import SqliteTelemetryStore


@pytest.fixture(autouse=True)
def clean_environment(tmp_path):
    """Ensure clean isolated environment before and after each test."""
    reset_watcher_state()
    reset_detection_state()
    # Reset in-memory repositories
    get_incident_repository().clear()
    get_evidence_repository().clear()
    yield
    reset_watcher_state()
    reset_detection_state()
    get_incident_repository().clear()
    get_evidence_repository().clear()


def make_test_event(
    event_id: str = None,
    project_id: str = "proj-test",
    service: str = "order-service",
    environment: str = "production",
    signal_type: SignalType = SignalType.LOG,
    source: str = "test-runner",
    level: str = "INFO",
    event_type: str = "test_event",
    message: str = "Test message",
    request_id: str = None,
    endpoint: str = None,
    status_code: int = None,
    exception_type: str = None,
    metadata: dict = None,
) -> TelemetryEvent:
    """Helper to construct immutable TelemetryEvent instances for testing."""
    now = datetime.now(timezone.utc)
    return TelemetryEvent(
        event_id=event_id or f"evt-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        service=service,
        environment=environment,
        signal_type=signal_type,
        source=source,
        timestamp=now,
        ingested_at=now,
        level=level,
        event_type=event_type,
        message=message,
        request_id=request_id,
        endpoint=endpoint,
        status_code=status_code,
        exception_type=exception_type,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 1. Deterministic Rule Tests
# ---------------------------------------------------------------------------


def test_health_check_failure_rule():
    """Verify HealthCheckFailureRule matches only health failures with proper failure signature."""
    rule = HealthCheckFailureRule()
    assert rule.rule_id == "rule.health_check_failed"

    # Match case
    evt_match = make_test_event(
        signal_type=SignalType.HEALTH,
        level="ERROR",
        event_type="health_check_failed",
        message="Probe timed out after 3.0s",
        endpoint="/healthz",
        metadata={"failure_type": "timeout", "http_status": None},
    )
    match = rule.evaluate(evt_match)
    assert match is not None
    assert match.rule_id == "rule.health_check_failed"
    assert match.severity == Severity.HIGH
    assert match.failure_signature == "timeout|/healthz"
    assert "Health Check Failed: order-service" in match.title
    assert "[Project: proj-test]" in match.summary

    # Non-match case: healthy probe
    evt_healthy = make_test_event(
        signal_type=SignalType.HEALTH,
        level="INFO",
        event_type="health_check_passed",
        message="Probe succeeded",
    )
    assert rule.evaluate(evt_healthy) is None

    # Non-match case: log event with health_check_failed event_type
    evt_log = make_test_event(
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="health_check_failed",
    )
    assert rule.evaluate(evt_log) is None


def test_app_error_rule_generic_and_exception():
    """Correction 2: Verify AppErrorRule detects generic application ERROR logs without exception_type."""
    rule = AppErrorRule()
    assert rule.rule_id == "rule.app_error"

    # Case A: Generic application ERROR log without exception_type or order_processing_failed
    evt_generic_err = make_test_event(
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="payment_gateway_down",
        message="Remote payment gateway returned 502 Bad Gateway",
        endpoint="/checkout",
        exception_type=None,
    )
    match_generic = rule.evaluate(evt_generic_err)
    assert match_generic is not None
    assert match_generic.rule_id == "rule.app_error"
    assert match_generic.severity == Severity.HIGH
    assert match_generic.failure_signature == "payment_gateway_down|/checkout"
    assert "Application Error in order-service: payment_gateway_down" in match_generic.title
    assert "[Project: proj-test]" in match_generic.summary

    # Case B: Application ERROR log with unhandled exception
    evt_exception = make_test_event(
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_processing_failed",
        message="Failed to process order 99",
        endpoint="/orders",
        exception_type="OrderProcessingError",
    )
    match_exc = rule.evaluate(evt_exception)
    assert match_exc is not None
    assert match_exc.failure_signature == "OrderProcessingError|/orders"
    assert "OrderProcessingError" in match_exc.title

    # Case C: Non-error log does not match
    evt_info = make_test_event(
        signal_type=SignalType.LOG,
        level="INFO",
        event_type="order_completed",
    )
    assert rule.evaluate(evt_info) is None


def test_http_5xx_rule():
    """Priority 3: Verify Http5xxRule matches HTTP status >= 500 when level is not ERROR."""
    rule = Http5xxRule()
    assert rule.rule_id == "rule.http_5xx"

    # Match case: access log or custom metric with 500/502/503/504
    evt_503 = make_test_event(
        signal_type=SignalType.LOG,
        level="INFO",
        event_type="http_response",
        status_code=503,
        endpoint="/api/v1/catalog",
        message="Service Unavailable",
    )
    match = rule.evaluate(evt_503)
    assert match is not None
    assert match.rule_id == "rule.http_5xx"
    assert match.failure_signature == "503|/api/v1/catalog"
    assert "HTTP 503 Error on order-service /api/v1/catalog" in match.title
    assert "[Project: proj-test]" in match.summary

    # Exclusivity: level == ERROR is handled by AppErrorRule, not Http5xxRule
    evt_error_500 = make_test_event(
        signal_type=SignalType.LOG,
        level="ERROR",
        status_code=500,
        endpoint="/api/v1/catalog",
    )
    assert rule.evaluate(evt_error_500) is None

    # Status code < 500 does not match
    evt_404 = make_test_event(
        signal_type=SignalType.LOG,
        level="WARNING",
        status_code=404,
        endpoint="/api/v1/missing",
    )
    assert rule.evaluate(evt_404) is None


# ---------------------------------------------------------------------------
# 2. Rule Determinism & Priority Order Tests
# ---------------------------------------------------------------------------


def test_rule_priority_and_mutual_exclusivity():
    """Verify engine evaluates in strict priority: Health > AppError > Http5xx."""
    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    assert len(engine.rules) == 3
    assert engine.rules[0].rule_id == "rule.health_check_failed"
    assert engine.rules[1].rule_id == "rule.app_error"
    assert engine.rules[2].rule_id == "rule.http_5xx"

    # Health event with level=ERROR and status_code=500: Health rule must win, not AppError or Http5xx
    evt_health = make_test_event(
        signal_type=SignalType.HEALTH,
        level="ERROR",
        event_type="health_check_failed",
        status_code=500,
        endpoint="/healthz",
        metadata={"failure_type": "http_status_failure"},
    )
    res_health = engine.evaluate(evt_health)
    assert res_health.matched is True
    assert res_health.rule_id == "rule.health_check_failed"
    assert res_health.action == DetectionAction.INCIDENT_CREATED

    # Log event with level=ERROR and status_code=500: AppError rule must win over Http5xx
    evt_app_err = make_test_event(
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="unhandled_crash",
        status_code=500,
        endpoint="/crash",
    )
    res_app_err = engine.evaluate(evt_app_err)
    assert res_app_err.matched is True
    assert res_app_err.rule_id == "rule.app_error"
    assert res_app_err.action == DetectionAction.INCIDENT_CREATED


# ---------------------------------------------------------------------------
# 3. Duplicate Suppression & Project ID Isolation (Correction 1)
# ---------------------------------------------------------------------------


def test_suppression_fingerprint_includes_project_id():
    """Correction 1: Incidents must NOT be suppressed across different project IDs."""
    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    # Project A failure
    evt_proj_a = make_test_event(
        project_id="project-alpha",
        service="payment-svc",
        environment="prod",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="charge_failed",
        exception_type="StripeCardError",
        endpoint="/charge",
    )
    res_a = engine.evaluate(evt_proj_a)
    assert res_a.action == DetectionAction.INCIDENT_CREATED
    inc_a_id = res_a.incident_id

    # Project B identical failure (same service, env, exception, endpoint, but DIFFERENT project_id)
    evt_proj_b = make_test_event(
        project_id="project-beta",
        service="payment-svc",
        environment="prod",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="charge_failed",
        exception_type="StripeCardError",
        endpoint="/charge",
    )
    res_b = engine.evaluate(evt_proj_b)
    # Must NOT be suppressed: project-beta gets its own incident!
    assert res_b.action == DetectionAction.INCIDENT_CREATED
    assert res_b.incident_id != inc_a_id

    # Second event for Project A: MUST be suppressed against Project A incident
    evt_proj_a_repeat = make_test_event(
        project_id="project-alpha",
        service="payment-svc",
        environment="prod",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="charge_failed",
        exception_type="StripeCardError",
        endpoint="/charge",
    )
    res_a_repeat = engine.evaluate(evt_proj_a_repeat)
    assert res_a_repeat.action == DetectionAction.SUPPRESSED
    assert res_a_repeat.incident_id == inc_a_id

    metrics = engine.get_metrics()
    assert metrics["incidents_created_count"] == 2
    assert metrics["suppressions_count"] == 1


def test_suppression_lifecycle_recurrence_after_resolution():
    """When an incident is RESOLVED or CLOSED, recurrence creates a fresh incident."""
    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    evt = make_test_event(
        project_id="proj-1",
        service="auth-svc",
        environment="prod",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="token_generation_failed",
        exception_type="KeyExpiredError",
    )

    # 1. Initial event -> Creates incident
    res1 = engine.evaluate(evt)
    assert res1.action == DetectionAction.INCIDENT_CREATED
    inc1 = inc_service.get_incident(res1.incident_id)
    assert inc1.status == IncidentStatus.OPEN

    # 2. Second event while OPEN -> Suppressed
    res2 = engine.evaluate(evt)
    assert res2.action == DetectionAction.SUPPRESSED
    assert res2.incident_id == inc1.id

    # 3. Transition incident: OPEN -> INVESTIGATING -> Suppressed still
    inc_service.update_status(inc1.id, IncidentStatus.INVESTIGATING)
    res3 = engine.evaluate(evt)
    assert res3.action == DetectionAction.SUPPRESSED

    # 4. Transition incident: INVESTIGATING -> RESOLVED
    inc_service.update_status(inc1.id, IncidentStatus.RESOLVED)

    # 5. Subsequent failure occurs: recurrence creates a fresh incident
    res4 = engine.evaluate(evt)
    assert res4.action == DetectionAction.INCIDENT_CREATED
    assert res4.incident_id != inc1.id
    inc2 = inc_service.get_incident(res4.incident_id)
    assert inc2.status == IncidentStatus.OPEN


# ---------------------------------------------------------------------------
# 4. Evidence Attachment & Typing Tests
# ---------------------------------------------------------------------------


def test_triggering_telemetry_attached_as_evidence():
    """Initial triggering event attaches as Evidence with correct type and request_id."""
    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    # Case A: Runtime log with request_id = None (never fabricate synthetic request IDs!)
    evt_log = make_test_event(
        project_id="proj-demo",
        service="order-svc",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        request_id=None,
        message="Database deadlock detected",
        metadata={"table": "orders"},
    )
    res_log = engine.evaluate(evt_log)
    assert res_log.action == DetectionAction.INCIDENT_CREATED

    evidence_list = ev_repo.list_for_incident(res_log.incident_id)
    assert len(evidence_list) == 1
    ev = evidence_list[0]
    assert ev.type == EvidenceType.RUNTIME_LOG
    assert ev.request_id is None
    assert ev.metadata["triggering_event_id"] == evt_log.event_id
    assert ev.metadata["project_id"] == "proj-demo"
    assert ev.metadata["rule_id"] == "rule.app_error"
    assert ev.metadata["table"] == "orders"

    # Case B: Health probe failure creates Evidence with type HEALTH_CHECK
    evt_health = make_test_event(
        project_id="proj-demo",
        service="web-frontend",
        signal_type=SignalType.HEALTH,
        level="ERROR",
        event_type="health_check_failed",
        endpoint="/healthz",
        message="Connection refused",
        metadata={"failure_type": "connection_refused"},
    )
    res_health = engine.evaluate(evt_health)
    assert res_health.action == DetectionAction.INCIDENT_CREATED

    health_evidence = ev_repo.list_for_incident(res_health.incident_id)
    assert len(health_evidence) == 1
    ev_h = health_evidence[0]
    assert ev_h.type == EvidenceType.HEALTH_CHECK
    assert ev_h.request_id is None
    assert ev_h.metadata["failure_type"] == "connection_refused"


# ---------------------------------------------------------------------------
# 5. WatcherService Integration (Correction 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_ingest_event_triggers_detection(tmp_path):
    """Verify single event ingestion into WatcherService evaluates detection and creates incident."""
    db_file = str(tmp_path / "watcher_det.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=50)

    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    watcher = WatcherService(
        buffer=buffer,
        storage=storage,
        detection_engine=engine,
    )

    evt = make_test_event(
        project_id="proj-e2e",
        service="inventory-svc",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="out_of_stock_critical",
        message="Inventory exhausted for SKU 1042",
        endpoint="/stock/deduct",
    )

    await watcher.ingest_event(evt)

    # 1. Event in buffer
    assert buffer.size() == 1
    # 2. Event in SQLite
    assert storage.count() == 1
    # 3. Detection evaluated and incident created
    assert engine.get_metrics()["incidents_created_count"] == 1
    incidents = inc_service.list_incidents()
    assert len(incidents) == 1
    assert incidents[0].service == "inventory-svc"

    # Status response includes detection counters
    status = watcher.get_status()
    assert status.detection is not None
    assert status.detection["incidents_created_count"] == 1
    assert status.detection["evaluations_count"] == 1

    storage.close()


@pytest.mark.asyncio
async def test_watcher_ingest_batch_delegates_to_ingest_event(tmp_path):
    """Correction 3: Ingest_batch delegates to ingest_event for single canonical evaluation."""
    db_file = str(tmp_path / "watcher_batch.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=50)

    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    watcher = WatcherService(
        buffer=buffer,
        storage=storage,
        detection_engine=engine,
    )

    e1 = make_test_event(level="INFO", event_type="heartbeat")
    e2 = make_test_event(
        level="ERROR",
        event_type="db_timeout",
        exception_type="TimeoutException",
        endpoint="/query",
    )
    e3 = make_test_event(
        level="ERROR",
        event_type="db_timeout",
        exception_type="TimeoutException",
        endpoint="/query",
    )

    await watcher.ingest_batch([e1, e2, e3])

    # 3 events ingested
    assert buffer.size() == 3
    assert storage.count() == 3

    # Detection evaluated exactly 3 times
    metrics = engine.get_metrics()
    assert metrics["evaluations_count"] == 3
    assert metrics["matches_count"] == 2  # e2 and e3 matched
    assert metrics["incidents_created_count"] == 1  # e2 created incident
    assert metrics["suppressions_count"] == 1  # e3 was suppressed

    storage.close()


# ---------------------------------------------------------------------------
# 6. Failure Isolation & Config Toggle Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_failure_isolation(tmp_path):
    """Detection evaluation exception must never crash WatcherService or block telemetry storage."""
    db_file = str(tmp_path / "watcher_iso.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=50)

    class FaultyDetectionEngine:
        def evaluate(self, event):
            raise RuntimeError("Database deadlock inside detection engine")

    watcher = WatcherService(
        buffer=buffer,
        storage=storage,
        detection_engine=FaultyDetectionEngine(),
    )

    evt = make_test_event(level="ERROR", event_type="crash")

    # Ingesting must NOT raise an exception
    await watcher.ingest_event(evt)

    # Telemetry was still saved despite detection failure
    assert buffer.size() == 1
    assert storage.count() == 1

    storage.close()


def test_detection_enabled_config_toggle():
    """When DETECTION_ENABLED=False, evaluate returns NO_MATCH and no incident is created."""
    object.__setattr__(config, "detection_enabled", False)
    try:
        inc_repo = InMemoryIncidentRepository()
        inc_service = IncidentService(inc_repo)
        ev_repo = InMemoryEvidenceRepository()
        engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

        evt = make_test_event(level="ERROR", event_type="order_failed")
        res = engine.evaluate(evt)

        assert res.matched is False
        assert res.action == DetectionAction.NO_MATCH
        assert len(inc_service.list_incidents()) == 0
        assert engine.get_metrics()["evaluations_count"] == 0
    finally:
        object.__setattr__(config, "detection_enabled", True)


@pytest.mark.asyncio
async def test_health_collector_probe_failure_triggers_automatic_incident(tmp_path):
    """Verify failing health probe emitted by HealthCheckCollector creates incident automatically."""
    import httpx

    db_file = str(tmp_path / "watcher_health_det.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=50)

    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    # Health collector pointing to an endpoint returning 503
    def failing_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"status": "down"})

    collector = HealthCheckCollector(
        health_url="http://mock-service.local/healthz",
        project_id="proj-prod",
        service="payment-gw",
        environment="production",
        probe_interval_seconds=0.05,
    )
    collector._client = httpx.AsyncClient(
        transport=httpx.MockTransport(failing_transport),
        timeout=1.0,
    )

    watcher = WatcherService(
        buffer=buffer,
        storage=storage,
        collectors=[collector],
        detection_engine=engine,
    )

    # Poll probe once directly through the collector
    await collector.start(watcher.ingest_event)
    await collector.probe_once()

    # Verify incident was automatically created
    incidents = inc_service.list_incidents()
    assert len(incidents) == 1
    inc = incidents[0]
    assert inc.service == "payment-gw"
    assert "Health Check Failed: payment-gw" in inc.title

    # Verify evidence attached
    ev_list = ev_repo.list_for_incident(inc.id)
    assert len(ev_list) == 1
    assert ev_list[0].type == EvidenceType.HEALTH_CHECK

    await collector.stop()
    storage.close()


@pytest.mark.asyncio
async def test_jsonl_collector_tailing_error_triggers_automatic_incident(tmp_path):
    """Verify application error logged to file and captured by JsonlFileCollector creates incident."""
    from app.watcher.collectors.file_collector import JsonlFileCollector

    db_file = str(tmp_path / "watcher_file_det.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=50)

    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(inc_repo)
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    watcher = WatcherService(
        buffer=buffer,
        storage=storage,
        detection_engine=engine,
    )

    log_file = str(tmp_path / "app_error.jsonl")
    with open(log_file, "w", encoding="utf-8") as f:
        pass

    collector = JsonlFileCollector(
        log_path=log_file,
        project_id="proj-analytics",
        service="etl-worker",
        environment="staging",
        poll_interval_seconds=0.05,
    )
    await collector.start(watcher.ingest_event)

    # Append an ERROR line to the file
    error_line = {
        "timestamp": "2026-10-01T12:00:00Z",
        "level": "ERROR",
        "event": "batch_processing_failed",
        "message": "Deadlock encountered on batch 987",
        "exception_type": "DeadlockException",
        "endpoint": "/jobs/run",
        "metadata": {"batch_id": 987},
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(error_line) + "\n")

    # Poll once
    await collector.poll_once()

    # Verify incident created
    incidents = inc_service.list_incidents()
    assert len(incidents) == 1
    assert incidents[0].service == "etl-worker"
    assert "Application Error in etl-worker: DeadlockException" in incidents[0].title

    # Verify evidence attached
    ev_list = ev_repo.list_for_incident(incidents[0].id)
    assert len(ev_list) == 1
    assert ev_list[0].type == EvidenceType.RUNTIME_LOG
    assert ev_list[0].metadata["batch_id"] == 987

    await collector.stop()
    storage.close()
