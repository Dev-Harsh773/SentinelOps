"""Comprehensive test suite for Stage 12 — Correlation + Rolling Evidence Windows."""

import asyncio
from datetime import datetime, timedelta, timezone
import uuid
import pytest

from app.common.config import config
from app.correlation.dependencies import get_correlation_engine, reset_correlation_state
from app.correlation.engine import CorrelationEngine
from app.detection.dependencies import get_detection_engine, reset_detection_state
from app.detection.engine import DetectionEngine
from app.detection.models import DetectionAction
from app.incidents.dependencies import (
    close_incident_repository,
    get_incident_repository,
    get_incident_service,
    set_custom_incident_db_path,
)
from app.incidents.models import IncidentStatus, Severity
from app.incidents.repository import InMemoryIncidentRepository
from app.incidents.service import IncidentService
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.models import EvidenceType
from app.telemetry.repository import InMemoryEvidenceRepository
from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.dependencies import reset_watcher_state
from app.watcher.models import SignalType, TelemetryEvent
from app.watcher.service import WatcherService
from app.watcher.storage import SqliteTelemetryStore


@pytest.fixture(autouse=True)
def clean_environment(tmp_path):
    """Ensure clean isolated environment before and after each test."""
    test_db = str(tmp_path / "sentinelops_test.db")
    set_custom_incident_db_path(test_db)
    reset_watcher_state()
    reset_detection_state()
    reset_correlation_state()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    yield
    reset_watcher_state()
    reset_detection_state()
    reset_correlation_state()
    get_incident_repository().clear()
    close_incident_repository()
    set_custom_incident_db_path(None)
    get_evidence_repository().clear()


def make_event(
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
    trace_id: str = None,
    endpoint: str = None,
    status_code: int = None,
    exception_type: str = None,
    timestamp: datetime = None,
    metadata: dict = None,
) -> TelemetryEvent:
    """Helper to construct immutable TelemetryEvent instances for testing."""
    now = timestamp or datetime.now(timezone.utc)
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
        trace_id=trace_id,
        endpoint=endpoint,
        status_code=status_code,
        exception_type=exception_type,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 1. Primary Real-World Stage 12 Case: OrderProcessingError + HTTP 500
# ---------------------------------------------------------------------------


def test_primary_case_application_error_and_http_500_correlate():
    """A failed /orders request with OrderProcessingError and HTTP 500 produces 1 incident with 2 evidence items."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    buffer = RollingTelemetryBuffer(capacity=100)
    engine = DetectionEngine(
        incident_service=inc_service,
        evidence_repository=ev_repo,
        buffer=buffer,
    )

    t0 = datetime.now(timezone.utc)
    req_id = "req-order-1042"

    # Event 1: Application-level exception log
    e1 = make_event(
        project_id="proj-demo",
        service="demo-app",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_processing_failed",
        exception_type="OrderProcessingError",
        request_id=req_id,
        endpoint="/orders",
        timestamp=t0,
    )

    # Event 2: HTTP 500 completion log
    e2 = make_event(
        project_id="proj-demo",
        service="demo-app",
        signal_type=SignalType.LOG,
        level="INFO",
        event_type="http_response",
        status_code=500,
        request_id=req_id,
        endpoint="/orders",
        timestamp=t0 + timedelta(milliseconds=50),
    )

    # Ingest e1
    res1 = engine.evaluate(e1)
    assert res1.action == DetectionAction.INCIDENT_CREATED
    inc_id = res1.incident_id
    assert inc_id is not None

    # Ingest e2
    res2 = engine.evaluate(e2)
    assert res2.action == DetectionAction.CORRELATED
    assert res2.incident_id == inc_id

    # Verify only ONE incident exists
    incidents = inc_service.list_incidents()
    assert len(incidents) == 1
    assert incidents[0].id == inc_id

    # Verify BOTH events are attached as evidence
    evidence = ev_repo.list_for_incident(inc_id)
    assert len(evidence) == 2
    events_in_ev = {ev.event for ev in evidence}
    assert "order_processing_failed" in events_in_ev
    assert "http_response" in events_in_ev


def test_reverse_arrival_order_still_correlates():
    """If HTTP 500 completion log arrives before OrderProcessingError, they still correlate into 1 incident."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    buffer = RollingTelemetryBuffer(capacity=100)
    engine = DetectionEngine(
        incident_service=inc_service,
        evidence_repository=ev_repo,
        buffer=buffer,
    )

    t0 = datetime.now(timezone.utc)
    req_id = "req-reverse-order"

    e_http = make_event(
        signal_type=SignalType.LOG,
        level="INFO",
        status_code=500,
        request_id=req_id,
        endpoint="/orders",
        timestamp=t0,
    )
    e_err = make_event(
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_processing_failed",
        exception_type="OrderProcessingError",
        request_id=req_id,
        endpoint="/orders",
        timestamp=t0 - timedelta(milliseconds=20),
    )

    res_http = engine.evaluate(e_http)
    assert res_http.action == DetectionAction.INCIDENT_CREATED
    inc_id = res_http.incident_id

    res_err = engine.evaluate(e_err)
    assert res_err.action == DetectionAction.CORRELATED
    assert res_err.incident_id == inc_id

    assert len(inc_service.list_incidents()) == 1
    assert len(ev_repo.list_for_incident(inc_id)) == 2


# ---------------------------------------------------------------------------
# 2. Dual-Key Strong Correlation (request_id + trace_id)
# ---------------------------------------------------------------------------


def test_dual_key_registration_and_lookup():
    """Trigger with both request_id and trace_id allows subsequent event with only trace_id to correlate."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    # Trigger with BOTH keys
    e1 = make_event(
        level="ERROR",
        event_type="crash_one",
        request_id="req-abc",
        trace_id="trace-xyz",
    )
    res1 = engine.evaluate(e1)
    assert res1.action == DetectionAction.INCIDENT_CREATED
    inc_id = res1.incident_id

    # Later event has NO request_id, but has matching trace_id
    e2 = make_event(
        level="ERROR",
        event_type="crash_two",
        request_id=None,
        trace_id="trace-xyz",
    )
    res2 = engine.evaluate(e2)
    assert res2.action == DetectionAction.CORRELATED
    assert res2.incident_id == inc_id

    assert len(inc_service.list_incidents()) == 1
    assert len(ev_repo.list_for_incident(inc_id)) == 2


# ---------------------------------------------------------------------------
# 3. Normal / INFO Telemetry in Post-Trigger Active Window (Mandatory Issue 1)
# ---------------------------------------------------------------------------


def test_normal_telemetry_attaches_during_active_post_window():
    """Mandatory Issue 1: Normal INFO telemetry sharing request_id attaches as contextual evidence."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    req_id = "req-normal-post"

    # Step 1: Abnormal event creates incident
    e_err = make_event(
        level="ERROR",
        event_type="app_failure",
        request_id=req_id,
    )
    res_err = engine.evaluate(e_err)
    assert res_err.action == DetectionAction.INCIDENT_CREATED
    inc_id = res_err.incident_id

    # Step 2: Normal INFO log with same request_id arrives
    e_info = make_event(
        level="INFO",
        event_type="cleanup_finished",
        message="Graceful cleanup completed for request",
        request_id=req_id,
    )
    res_info = engine.evaluate(e_info)
    # Must NOT create an incident, but MUST correlate and attach as contextual evidence!
    assert res_info.action == DetectionAction.CORRELATED
    assert res_info.incident_id == inc_id

    assert len(inc_service.list_incidents()) == 1
    ev_list = ev_repo.list_for_incident(inc_id)
    assert len(ev_list) == 2
    assert any(ev.event == "cleanup_finished" and ev.level == "INFO" for ev in ev_list)


def test_normal_telemetry_without_active_incident_creates_no_incident():
    """Mandatory Issue 1: Non-abnormal events without an active incident match NEVER create incidents."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    e_info = make_event(level="INFO", event_type="routine_log", request_id="req-unrelated")
    res = engine.evaluate(e_info)

    assert res.matched is False
    assert res.action == DetectionAction.NO_MATCH
    assert len(inc_service.list_incidents()) == 0
    assert len(ev_repo.list_for_incident("any")) == 0


# ---------------------------------------------------------------------------
# 4. Isolation Guarantees: Request ID & Cross-Project
# ---------------------------------------------------------------------------


def test_different_request_ids_create_separate_incidents():
    """Two identical errors on the same endpoint/service with different request_ids must produce 2 separate incidents."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    e1 = make_event(
        project_id="stage12-request-isolation-final",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id="final-req-A",
    )
    e2 = make_event(
        project_id="stage12-request-isolation-final",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id="final-req-B",
    )

    res1 = engine.evaluate(e1)
    res2 = engine.evaluate(e2)

    assert res1.action == DetectionAction.INCIDENT_CREATED
    assert res2.action == DetectionAction.INCIDENT_CREATED
    assert res1.incident_id != res2.incident_id
    assert len(inc_service.list_incidents()) == 2


def test_same_request_id_suppresses_duplicate():
    """Same failure event repeated with the exact same request_id must be suppressed into the existing incident."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    e1 = make_event(
        project_id="stage12-suppress-test",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id="final-req-A",
    )
    e2 = make_event(
        project_id="stage12-suppress-test",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id="final-req-A",
    )

    res1 = engine.evaluate(e1)
    res2 = engine.evaluate(e2)

    assert res1.action == DetectionAction.INCIDENT_CREATED
    assert res2.action == DetectionAction.SUPPRESSED
    assert res2.incident_id == res1.incident_id
    assert len(inc_service.list_incidents()) == 1
    assert len(ev_repo.list_for_incident(res1.incident_id)) == 1


def test_different_trace_ids_without_request_id_create_separate_incidents():
    """Two identical errors without request_id but with different trace_id values produce 2 separate incidents."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    e1 = make_event(
        project_id="stage12-trace-test",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id=None,
        trace_id="trace-001",
    )
    e2 = make_event(
        project_id="stage12-trace-test",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id=None,
        trace_id="trace-002",
    )

    res1 = engine.evaluate(e1)
    res2 = engine.evaluate(e2)

    assert res1.action == DetectionAction.INCIDENT_CREATED
    assert res2.action == DetectionAction.INCIDENT_CREATED
    assert res1.incident_id != res2.incident_id
    assert len(inc_service.list_incidents()) == 2


def test_same_trace_id_suppresses_duplicate():
    """Same failure event repeated with the exact same trace_id must be suppressed into the existing incident."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    e1 = make_event(
        project_id="stage12-trace-test",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id=None,
        trace_id="trace-001",
    )
    e2 = make_event(
        project_id="stage12-trace-test",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id=None,
        trace_id="trace-001",
    )

    res1 = engine.evaluate(e1)
    res2 = engine.evaluate(e2)

    assert res1.action == DetectionAction.INCIDENT_CREATED
    assert res2.action == DetectionAction.SUPPRESSED
    assert res2.incident_id == res1.incident_id
    assert len(inc_service.list_incidents()) == 1


def test_legacy_no_id_duplicate_suppression():
    """Identical errors without request_id and without trace_id are duplicate-suppressed."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    e1 = make_event(
        project_id="stage12-noid-test",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id=None,
        trace_id=None,
    )
    e2 = make_event(
        project_id="stage12-noid-test",
        service="orders-final",
        environment="development",
        signal_type=SignalType.LOG,
        level="ERROR",
        event_type="order_failed",
        endpoint="/orders-final",
        exception_type="OrderProcessingError",
        request_id=None,
        trace_id=None,
    )

    res1 = engine.evaluate(e1)
    res2 = engine.evaluate(e2)

    assert res1.action == DetectionAction.INCIDENT_CREATED
    assert res2.action == DetectionAction.SUPPRESSED
    assert res2.incident_id == res1.incident_id
    assert len(inc_service.list_incidents()) == 1


def test_cross_project_isolation():
    """Identical request_id across project-A and project-B must NEVER correlate or share evidence."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    shared_req_id = "req-shared-uuid"

    e_proj_a = make_event(
        project_id="project-alpha",
        service="order-svc",
        level="ERROR",
        request_id=shared_req_id,
    )
    e_proj_b = make_event(
        project_id="project-beta",
        service="order-svc",
        level="ERROR",
        request_id=shared_req_id,
    )

    res_a = engine.evaluate(e_proj_a)
    res_b = engine.evaluate(e_proj_b)

    assert res_a.action == DetectionAction.INCIDENT_CREATED
    assert res_b.action == DetectionAction.INCIDENT_CREATED
    assert res_a.incident_id != res_b.incident_id

    ev_a = ev_repo.list_for_incident(res_a.incident_id)
    ev_b = ev_repo.list_for_incident(res_b.incident_id)
    assert len(ev_a) == 1 and ev_a[0].metadata["project_id"] == "project-alpha"
    assert len(ev_b) == 1 and ev_b[0].metadata["project_id"] == "project-beta"


# ---------------------------------------------------------------------------
# 5. Fallback Correlation: Telemetry Time Anchor (Mandatory Issue 3)
# ---------------------------------------------------------------------------


def test_fallback_correlation_telemetry_timestamp_anchor():
    """Fallback correlation evaluates telemetry occurrence time against non-sliding anchor timestamp."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Event 1 at T0 (no request_id, endpoint /orders)
    e1 = make_event(
        level="ERROR",
        event_type="gateway_timeout",
        endpoint="/orders",
        request_id=None,
        timestamp=t0,
    )
    res1 = engine.evaluate(e1)
    assert res1.action == DetectionAction.INCIDENT_CREATED
    inc_id = res1.incident_id

    # Event 2 at T0 + 5s (within 10s fallback window of anchor)
    e2 = make_event(
        level="INFO",
        status_code=504,
        endpoint="/orders",
        request_id=None,
        timestamp=t0 + timedelta(seconds=5),
    )
    res2 = engine.evaluate(e2)
    assert res2.action == DetectionAction.CORRELATED
    assert res2.incident_id == inc_id

    # Event 3 at T0 + 15s (outside 10s fallback window of anchor T0, distinct failure signature)
    e3 = make_event(
        level="ERROR",
        event_type="database_unavailable",
        endpoint="/orders",
        request_id=None,
        timestamp=t0 + timedelta(seconds=15),
    )
    res3 = engine.evaluate(e3)
    # Non-sliding anchor prevents event chaining: e3 must NOT correlate to Incident 1!
    assert res3.incident_id != inc_id
    assert len(inc_service.list_incidents()) == 2


def test_endpoint_mismatch_prevents_fallback_correlation():
    """Events without request_id on different endpoints must NEVER merge under fallback correlation."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    t0 = datetime.now(timezone.utc)
    e_orders = make_event(level="ERROR", endpoint="/orders", timestamp=t0)
    e_checkout = make_event(level="ERROR", endpoint="/checkout", timestamp=t0 + timedelta(seconds=1))

    res1 = engine.evaluate(e_orders)
    res2 = engine.evaluate(e_checkout)

    assert res1.incident_id != res2.incident_id
    assert len(inc_service.list_incidents()) == 2


# ---------------------------------------------------------------------------
# 6. Pre-Trigger Window Harvesting & Trigger Exclusion (Mandatory Issue 2)
# ---------------------------------------------------------------------------


def test_pre_trigger_harvesting_excludes_trigger_event():
    """Mandatory Issue 2: Pre-window harvesting excludes candidate.event_id == triggering_event.event_id."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    buffer = RollingTelemetryBuffer(capacity=50)
    engine = DetectionEngine(
        incident_service=inc_service,
        evidence_repository=ev_repo,
        buffer=buffer,
    )

    t0 = datetime.now(timezone.utc)
    req_id = "req-pre-harvest"

    # Pre-trigger INFO log in buffer
    e_info = make_event(
        level="INFO",
        event_type="order_initiated",
        request_id=req_id,
        timestamp=t0 - timedelta(seconds=2),
    )
    buffer.append(e_info)

    # Triggering event is also appended to buffer (mimicking WatcherService.ingest_event)
    e_trigger = make_event(
        level="ERROR",
        event_type="order_failed",
        request_id=req_id,
        timestamp=t0,
    )
    buffer.append(e_trigger)

    # Ingest trigger event
    res = engine.evaluate(e_trigger)
    assert res.action == DetectionAction.INCIDENT_CREATED

    evidence = ev_repo.list_for_incident(res.incident_id)
    # Total evidence should be exactly 2: e_trigger (Slot 1) + e_info (pre-window)
    assert len(evidence) == 2

    # Verify triggering event is NOT duplicated
    trigger_evs = [ev for ev in evidence if ev.metadata.get("triggering_event_id") == e_trigger.event_id]
    assert len(trigger_evs) == 1
    assert trigger_evs[0].metadata["correlation_role"] == "trigger"


def test_pre_trigger_harvesting_excludes_unrelated_events():
    """Pre-window harvesting only grabs events matching request_id, excluding unrelated logs."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    buffer = RollingTelemetryBuffer(capacity=50)
    engine = DetectionEngine(
        incident_service=inc_service,
        evidence_repository=ev_repo,
        buffer=buffer,
    )

    t0 = datetime.now(timezone.utc)

    # Unrelated INFO log in buffer
    buffer.append(
        make_event(level="INFO", event_type="unrelated_ping", request_id="req-other", timestamp=t0 - timedelta(seconds=5))
    )

    # Trigger event
    e_trigger = make_event(level="ERROR", event_type="crash", request_id="req-mine", timestamp=t0)
    buffer.append(e_trigger)

    res = engine.evaluate(e_trigger)
    evidence = ev_repo.list_for_incident(res.incident_id)

    # Only the trigger event should be attached; unrelated_ping must NOT be attached
    assert len(evidence) == 1
    assert evidence[0].request_id == "req-mine"


# ---------------------------------------------------------------------------
# 7. Total Evidence Cap & Deduplication
# ---------------------------------------------------------------------------


def test_total_evidence_cap_enforced():
    """Total evidence attached to an incident never exceeds CORRELATION_MAX_EVIDENCE_PER_INCIDENT."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    req_id = "req-flood"

    # Trigger event (Slot 1)
    e1 = make_event(level="ERROR", event_type="err_0", request_id=req_id)
    res = engine.evaluate(e1)
    inc_id = res.incident_id

    # Emit 25 additional distinct correlated events
    for i in range(1, 26):
        e = make_event(level="INFO", event_type=f"log_{i}", request_id=req_id)
        engine.evaluate(e)

    evidence = ev_repo.list_for_incident(inc_id)
    # Strictly capped at default 20
    assert len(evidence) == config.correlation_max_evidence_per_incident
    # Slot 1 trigger is preserved
    assert evidence[0].metadata["correlation_role"] == "trigger"


def test_evidence_fingerprint_deduplication():
    """Re-emitting an identical event does not create duplicate evidence records."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    req_id = "req-dedup"
    e1 = make_event(level="ERROR", event_type="app_error", request_id=req_id)

    res1 = engine.evaluate(e1)
    res2 = engine.evaluate(e1)

    assert res1.action == DetectionAction.INCIDENT_CREATED
    assert res2.action == DetectionAction.SUPPRESSED

    evidence = ev_repo.list_for_incident(res1.incident_id)
    assert len(evidence) == 1


# ---------------------------------------------------------------------------
# 8. Post-Trigger Process Time Expiry (Mandatory Issue 3)
# ---------------------------------------------------------------------------


def test_backdated_telemetry_does_not_prematurely_expire_post_window():
    """Mandatory Issue 3: expires_at uses current UTC process time, so backdated telemetry has a full post window."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    # Event occurred 5 minutes ago in telemetry time
    old_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    req_id = "req-backdated"

    e_trigger = make_event(level="ERROR", request_id=req_id, timestamp=old_time)
    res = engine.evaluate(e_trigger)
    assert res.action == DetectionAction.INCIDENT_CREATED
    inc_id = res.incident_id

    # Followup event occurs now
    e_followup = make_event(level="INFO", request_id=req_id, timestamp=old_time + timedelta(seconds=1))
    res_followup = engine.evaluate(e_followup)

    # Must still correlate because process time has not exceeded 30s!
    assert res_followup.action == DetectionAction.CORRELATED
    assert res_followup.incident_id == inc_id


# ---------------------------------------------------------------------------
# 9. WatcherService Integration & Single Invocation (Mandatory Issue 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watcher_batch_ingest_delegates_to_single_invocation(tmp_path):
    """Mandatory Issue 1: Ingesting batch delegates to ingest_event, calling correlation exactly once per event."""
    db_file = str(tmp_path / "watcher_corr_batch.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=50)

    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    corr_engine = CorrelationEngine(
        incident_service=inc_service,
        evidence_repository=ev_repo,
        buffer=buffer,
    )
    det_engine = DetectionEngine(
        incident_service=inc_service,
        evidence_repository=ev_repo,
        correlation_engine=corr_engine,
        buffer=buffer,
    )
    watcher = WatcherService(
        buffer=buffer,
        storage=storage,
        detection_engine=det_engine,
    )

    req_id = "req-batch-corr"
    e1 = make_event(level="ERROR", event_type="err_first", request_id=req_id)
    e2 = make_event(level="INFO", status_code=500, request_id=req_id)

    await watcher.ingest_batch([e1, e2])

    # Exactly 1 incident created
    incidents = inc_service.list_incidents()
    assert len(incidents) == 1

    # Exactly 2 evidence items attached
    evidence = ev_repo.list_for_incident(incidents[0].id)
    assert len(evidence) == 2

    # Verification of metrics
    metrics = corr_engine.get_metrics()
    assert metrics["evaluations_count"] == 2
    assert metrics["incidents_created_count"] == 1
    assert metrics["correlated_events_count"] == 1

    storage.close()


# ---------------------------------------------------------------------------
# 10. Lifecycle Recurrence & Failure Isolation
# ---------------------------------------------------------------------------


def test_recurrence_after_resolution_creates_fresh_incident():
    """Transitioning incident to RESOLVED invalidates correlation and allows a fresh incident."""
    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    engine = DetectionEngine(incident_service=inc_service, evidence_repository=ev_repo)

    req_id = "req-recurrence"
    e = make_event(level="ERROR", event_type="flaky_error", request_id=req_id)

    res1 = engine.evaluate(e)
    assert res1.action == DetectionAction.INCIDENT_CREATED
    inc1_id = res1.incident_id

    # Resolve incident
    inc_service.update_status(inc1_id, IncidentStatus.RESOLVED)

    # Flaky error recurs
    res2 = engine.evaluate(e)
    assert res2.action == DetectionAction.INCIDENT_CREATED
    assert res2.incident_id != inc1_id
    assert len(inc_service.list_incidents()) == 2


@pytest.mark.asyncio
async def test_correlation_failure_isolation(tmp_path):
    """An unexpected exception inside correlation engine does not crash WatcherService or block persistence."""
    db_file = str(tmp_path / "watcher_corr_iso.db")
    storage = SqliteTelemetryStore(db_path=db_file)
    buffer = RollingTelemetryBuffer(capacity=50)

    class BrokenCorrelationEngine:
        def observe(self, event, match):
            raise RuntimeError("Correlation database locked")

    inc_service = IncidentService(InMemoryIncidentRepository())
    ev_repo = InMemoryEvidenceRepository()
    det_engine = DetectionEngine(
        incident_service=inc_service,
        evidence_repository=ev_repo,
        correlation_engine=BrokenCorrelationEngine(),
    )
    watcher = WatcherService(buffer=buffer, storage=storage, detection_engine=det_engine)

    e = make_event(level="ERROR", event_type="crash")
    # Must NOT raise exception
    await watcher.ingest_event(e)

    # Telemetry persisted despite correlation error
    assert buffer.size() == 1
    assert storage.count() == 1
    storage.close()
