"""Automated tests for Stage 3 — Telemetry and Evidence Collection."""

import json
from fastapi.testclient import TestClient
import pytest

from app.incidents.dependencies import get_incident_repository
from app.main import app as sentinelops_app
from app.telemetry.collector import RuntimeLogCollector
from app.telemetry.dependencies import get_evidence_repository, get_log_collector
from demo_app.common.event_logger import event_logger
from demo_app.failure_modes.controller import get_failure_controller
from demo_app.main import app as demo_app

sentinel_client = TestClient(sentinelops_app)
demo_client = TestClient(demo_app)


@pytest.fixture(autouse=True)
def reset_repositories_and_failures():
    """Ensure in-memory repositories, dependency overrides, and failure modes are reset."""
    sentinelops_app.dependency_overrides.clear()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_failure_controller().reset()
    yield
    sentinelops_app.dependency_overrides.clear()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    get_failure_controller().reset()


def create_test_incident(title: str = "Test Incident") -> str:
    """Helper to create an incident in SentinelOps and return its UUID."""
    res = sentinel_client.post(
        "/incidents",
        json={
            "title": title,
            "summary": "Sample incident summary for telemetry testing.",
            "severity": "high",
            "service": "demo-app",
            "environment": "development",
        },
    )
    assert res.status_code == 201
    return res.json()["id"]


def test_demo_app_jsonl_generation(tmp_path, monkeypatch):
    """Verify demo application appends structured JSONL events upon controlled failure."""
    test_log_file = tmp_path / "test_demo_app.jsonl"
    monkeypatch.setattr(event_logger, "_log_path", str(test_log_file))

    # Enable failure mode
    demo_client.post("/admin/failures/order-processing/enable")

    # Trigger failure
    res = demo_client.post("/orders", json={"product_id": "p1", "quantity": 1})
    assert res.status_code == 500
    req_id = res.headers["x-request-id"]

    # Verify log file exists and contains the structured failure event
    assert test_log_file.exists()
    lines = [json.loads(line) for line in test_log_file.read_text(encoding="utf-8").strip().split("\n")]
    events = [l["event"] for l in lines]

    assert "order_processing_failed" in events
    failure_record = next(l for l in lines if l["event"] == "order_processing_failed")

    assert failure_record["service"] == "demo-app"
    assert failure_record["request_id"] == req_id
    assert failure_record["endpoint"] == "/orders"
    assert failure_record["level"] == "ERROR"
    assert failure_record["exception_type"] == "OrderProcessingError"
    assert "Simulated payment gateway timeout" in failure_record["message"]
    assert "traceback" in failure_record["metadata"]


def test_collect_evidence_success(tmp_path):
    """Verify SentinelOps collects matching runtime failure event and attaches it to an incident."""
    test_log = tmp_path / "runtime.jsonl"
    req_id = "test-req-12345"

    # Write a structured failure event
    event = {
        "timestamp": "2026-09-23T10:15:30.500000Z",
        "level": "ERROR",
        "service": "demo-app",
        "request_id": req_id,
        "method": "POST",
        "endpoint": "/orders",
        "event": "order_processing_failed",
        "message": "Simulated payment gateway timeout during order checkout.",
        "status_code": 500,
        "exception_type": "OrderProcessingError",
        "metadata": {"traceback": "Traceback mock..."},
    }
    test_log.write_text(json.dumps(event) + "\n", encoding="utf-8")

    # FastAPI dependency override
    sentinelops_app.dependency_overrides[get_log_collector] = lambda: RuntimeLogCollector(log_path=str(test_log))

    incident_id = create_test_incident()

    # Collect evidence
    collect_res = sentinel_client.post(
        f"/incidents/{incident_id}/evidence/collect",
        json={"request_id": req_id},
    )
    assert collect_res.status_code == 200
    data = collect_res.json()
    assert data["incident_id"] == incident_id
    assert data["request_id"] == req_id
    assert data["collected"] == 1
    assert len(data["evidence"]) == 1

    ev = data["evidence"][0]
    assert ev["incident_id"] == incident_id
    assert ev["request_id"] == req_id
    assert ev["service"] == "demo-app"
    assert ev["type"] == "runtime_log"
    assert ev["source"] == "demo-app-runtime-log"
    assert ev["event"] == "order_processing_failed"
    assert ev["exception_type"] == "OrderProcessingError"
    assert ev["level"] == "ERROR"
    assert ev["endpoint"] == "/orders"
    assert "Simulated payment gateway timeout" in ev["message"]
    # Metadata preserves traceback
    assert ev["metadata"]["traceback"] == "Traceback mock..."
    # Verify timestamp preserves runtime occurrence time (UTC)
    assert "2026-09-23T10:15:30" in ev["timestamp"]
    # Created at is populated
    assert "created_at" in ev

    # Verify incident status was NOT modified during evidence collection
    inc_res = sentinel_client.get(f"/incidents/{incident_id}")
    assert inc_res.json()["status"] == "open"


def test_list_evidence(tmp_path):
    """Verify GET /incidents/{incident_id}/evidence returns attached evidence."""
    test_log = tmp_path / "runtime.jsonl"
    req_id = "req-list-test"
    event = {
        "timestamp": "2026-09-23T12:00:00Z",
        "level": "ERROR",
        "service": "demo-app",
        "request_id": req_id,
        "method": "POST",
        "endpoint": "/orders",
        "event": "order_processing_failed",
        "message": "Payment timeout",
        "exception_type": "OrderProcessingError",
        "metadata": {},
    }
    test_log.write_text(json.dumps(event) + "\n", encoding="utf-8")
    sentinelops_app.dependency_overrides[get_log_collector] = lambda: RuntimeLogCollector(log_path=str(test_log))

    incident_id = create_test_incident()

    # Initially empty list
    empty_res = sentinel_client.get(f"/incidents/{incident_id}/evidence")
    assert empty_res.status_code == 200
    assert empty_res.json() == []

    # Collect
    sentinel_client.post(
        f"/incidents/{incident_id}/evidence/collect",
        json={"request_id": req_id},
    )

    # Now list returns 1 record
    list_res = sentinel_client.get(f"/incidents/{incident_id}/evidence")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) == 1
    assert items[0]["request_id"] == req_id


def test_only_relevant_failure_evidence_persisted(tmp_path):
    """Verify that given request_received, order_processing_failed, and request_completed,

    only the meaningful failure event is converted into Incident Evidence, filtering out
    routine lifecycle noise.
    """
    test_log = tmp_path / "runtime.jsonl"
    req_id = "req-noise-filter"

    events = [
        {
            "timestamp": "2026-09-23T12:00:00Z",
            "level": "INFO",
            "service": "demo-app",
            "request_id": req_id,
            "method": "POST",
            "endpoint": "/orders",
            "event": "request_received",
            "message": "Received POST /orders",
            "metadata": {},
        },
        {
            "timestamp": "2026-09-23T12:00:01Z",
            "level": "ERROR",
            "service": "demo-app",
            "request_id": req_id,
            "method": "POST",
            "endpoint": "/orders",
            "event": "order_processing_failed",
            "message": "Gateway timeout",
            "exception_type": "OrderProcessingError",
            "metadata": {},
        },
        {
            "timestamp": "2026-09-23T12:00:02Z",
            "level": "INFO",
            "service": "demo-app",
            "request_id": req_id,
            "method": "POST",
            "endpoint": "/orders",
            "event": "request_completed",
            "message": "Completed with 500",
            "status_code": 500,
            "metadata": {},
        },
    ]
    test_log.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    sentinelops_app.dependency_overrides[get_log_collector] = lambda: RuntimeLogCollector(log_path=str(test_log))

    incident_id = create_test_incident()

    collect_res = sentinel_client.post(
        f"/incidents/{incident_id}/evidence/collect",
        json={"request_id": req_id},
    )
    assert collect_res.status_code == 200
    data = collect_res.json()
    assert data["collected"] == 1
    # Only order_processing_failed was stored
    assert data["evidence"][0]["event"] == "order_processing_failed"


def test_duplicate_collection_protection(tmp_path):
    """Verify calling collection twice for the same request ID does not duplicate identical records."""
    test_log = tmp_path / "runtime.jsonl"
    req_id = "req-duplicate-check"
    event = {
        "timestamp": "2026-09-23T12:00:00Z",
        "level": "ERROR",
        "service": "demo-app",
        "request_id": req_id,
        "method": "POST",
        "endpoint": "/orders",
        "event": "order_processing_failed",
        "message": "Error 1",
        "exception_type": "OrderProcessingError",
        "metadata": {},
    }
    test_log.write_text(json.dumps(event) + "\n", encoding="utf-8")
    sentinelops_app.dependency_overrides[get_log_collector] = lambda: RuntimeLogCollector(log_path=str(test_log))

    incident_id = create_test_incident()

    # First collection
    res1 = sentinel_client.post(f"/incidents/{incident_id}/evidence/collect", json={"request_id": req_id})
    assert res1.status_code == 200
    assert res1.json()["collected"] == 1

    # Second collection
    res2 = sentinel_client.post(f"/incidents/{incident_id}/evidence/collect", json={"request_id": req_id})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["collected"] == 0
    assert data2["evidence"] == []
    assert "already attached" in data2["message"].lower()

    # Verify repository holds only 1 record
    all_evidence = sentinel_client.get(f"/incidents/{incident_id}/evidence").json()
    assert len(all_evidence) == 1


def test_collect_evidence_missing_incident():
    """Verify attempting collection on non-existent incident returns HTTP 404."""
    res = sentinel_client.post(
        "/incidents/non-existent-uuid/evidence/collect",
        json={"request_id": "some-id"},
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_collect_evidence_unknown_request_id(tmp_path):
    """Verify unknown request ID returns HTTP 200 with collected=0 without fake evidence."""
    test_log = tmp_path / "runtime.jsonl"
    test_log.write_text(
        json.dumps({
            "timestamp": "2026-09-23T12:00:00Z",
            "level": "ERROR",
            "service": "demo-app",
            "request_id": "other-id",
            "method": "POST",
            "endpoint": "/orders",
            "event": "order_processing_failed",
            "message": "Error",
            "exception_type": "OrderProcessingError",
        })
        + "\n",
        encoding="utf-8",
    )
    sentinelops_app.dependency_overrides[get_log_collector] = lambda: RuntimeLogCollector(log_path=str(test_log))

    incident_id = create_test_incident()
    res = sentinel_client.post(
        f"/incidents/{incident_id}/evidence/collect",
        json={"request_id": "unknown-request-id"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["collected"] == 0
    assert data["evidence"] == []
    assert "no matching" in data["message"].lower()


def test_collector_handles_missing_log_file():
    """Verify non-existent log file returns HTTP 200 with collected=0 and clean message, not HTTP 500."""
    sentinelops_app.dependency_overrides[get_log_collector] = lambda: RuntimeLogCollector(
        log_path="non_existent_directory/missing.jsonl"
    )

    incident_id = create_test_incident()
    res = sentinel_client.post(
        f"/incidents/{incident_id}/evidence/collect",
        json={"request_id": "any-id"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["collected"] == 0
    assert "not available" in data["message"].lower()


def test_collector_handles_malformed_json_lines(tmp_path):
    """Verify malformed JSON lines are safely skipped while valid matching lines are processed."""
    test_log = tmp_path / "malformed.jsonl"
    req_id = "req-robustness"
    content = (
        '{"valid": "but_wrong_req", "request_id": "other"}\n'
        '{"corrupted JSON line that cannot be parsed\n'
        '   \n'
        + json.dumps({
            "timestamp": "2026-09-23T15:00:00Z",
            "level": "ERROR",
            "service": "demo-app",
            "request_id": req_id,
            "method": "POST",
            "endpoint": "/orders",
            "event": "order_processing_failed",
            "message": "Recovered from corrupted file",
            "exception_type": "OrderProcessingError",
        })
        + "\n"
    )
    test_log.write_text(content, encoding="utf-8")

    collector = RuntimeLogCollector(log_path=str(test_log))
    events = collector.collect_events_for_request(req_id)
    assert len(events) == 1
    assert events[0]["message"] == "Recovered from corrupted file"


def test_timestamp_parsing_validation(tmp_path):
    """Verify valid UTC timestamps are parsed and malformed timestamps are safely skipped."""
    test_log = tmp_path / "timestamps.jsonl"
    req_id = "req-ts-test"

    valid_event = {
        "timestamp": "2026-09-23T14:30:00Z",
        "level": "ERROR",
        "service": "demo-app",
        "request_id": req_id,
        "event": "order_processing_failed",
        "message": "Valid ts",
        "exception_type": "OrderProcessingError",
    }
    invalid_ts_event = {
        "timestamp": "not-a-valid-iso-timestamp",
        "level": "ERROR",
        "service": "demo-app",
        "request_id": req_id,
        "event": "order_processing_failed",
        "message": "Invalid ts",
        "exception_type": "OrderProcessingError",
    }

    test_log.write_text(
        json.dumps(invalid_ts_event) + "\n" + json.dumps(valid_event) + "\n",
        encoding="utf-8",
    )

    collector = RuntimeLogCollector(log_path=str(test_log))
    events = collector.collect_events_for_request(req_id)
    # The invalid timestamp was skipped, valid timestamp was kept
    assert len(events) == 1
    assert events[0]["message"] == "Valid ts"
    assert events[0]["_parsed_datetime"].year == 2026


def test_evidence_collect_request_validation():
    """Verify request_id validation: empty or whitespace-only is rejected with HTTP 422."""
    incident_id = create_test_incident()

    res1 = sentinel_client.post(
        f"/incidents/{incident_id}/evidence/collect",
        json={"request_id": "   "},
    )
    assert res1.status_code == 422

    res2 = sentinel_client.post(
        f"/incidents/{incident_id}/evidence/collect",
        json={"request_id": ""},
    )
    assert res2.status_code == 422
