"""Unit tests for Stage 19 Desktop Report, Timeline, and Operational Memory UI."""

import os
import sys
import pytest
import httpx
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

from desktop.api.client import SentinelOpsClient
from desktop.api.models import IncidentDTO, IncidentReportDTO, TimelineEventDTO, SimilarIncidentReportDTO
from desktop.state.app_state import AppState
from desktop.ui.views.incidents_view import IncidentsView
from desktop.workers.task_runner import TaskRunner


@pytest.fixture(scope="session")
def qapp():
    """Ensure headless offscreen Qt application exists for tests."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture(autouse=True)
def reset_desktop_state():
    """Ensure AppState singleton is reset for isolation across tests."""
    state = AppState()
    state._init_state()
    yield
    state._init_state()


def test_incident_report_dto_from_dict():
    """Verify IncidentReportDTO, TimelineEventDTO, and SimilarIncidentReportDTO parsing."""
    raw = {
        "incident": {
            "incident_id": "inc-dto-1",
            "project_id": "proj-1",
            "title": "Payment Degradation",
            "summary": "Gateway latency elevated",
            "severity": "high",
            "status": "investigating",
            "service": "payment-svc",
            "environment": "prod",
            "created_at": "2026-10-04T12:00:00Z",
            "updated_at": "2026-10-04T12:15:00Z",
            "duration_seconds": 900.0,
        },
        "detection_and_evidence": {
            "total_evidence_count": 2,
            "items": [
                {
                    "id": "ev-1",
                    "type": "runtime_log",
                    "source": "payment.log",
                    "timestamp": "2026-10-04T12:00:00Z",
                    "level": "ERROR",
                    "event": "timeout",
                    "message": "Gateway timed out after 5000ms",
                }
            ],
        },
        "investigation": {
            "investigation_id": "inv-1",
            "status": "completed",
            "root_cause_hypothesis": "Connection pool exhausted",
            "failure_location": "db/pool.py:42",
            "confidence": 0.95,
            "uncertainties": [],
            "relevant_files": ["db/pool.py"],
            "relevant_symbols": ["acquire_conn"],
        },
        "remediation": {
            "remediation_id": "rem-1",
            "status": "approved",
            "summary": "Increase pool size and add backpressure",
            "branch_name": "remediate-pool-size",
            "proposed_changes": [
                {
                    "file_path": "db/pool.py",
                    "change_type": "modify",
                    "description": "Increase default max connections to 50",
                    "reason": "Prevents pool starvation under load",
                }
            ],
        },
        "human_decisions": [
            {
                "decision_type": "remediation_review",
                "decision": "approved",
                "actor": "lead-sre",
                "comment_or_reason": "Approved configuration update",
                "timestamp": "2026-10-04T12:10:00Z",
                "target_id": "rem-1",
            }
        ],
        "safe_actions": [
            {
                "action_id": "act-1",
                "action_type": "test_connector",
                "target_type": "connector",
                "target_id": "conn-1",
                "risk_level": "low",
                "policy_status": "allowed",
                "approval_status": "approved",
                "execution_status": "succeeded",
                "created_at": "2026-10-04T12:05:00Z",
            }
        ],
        "notifications": [],
        "similar_incidents": [
            {
                "incident_id": "inc-past-1",
                "project_id": "proj-1",
                "title": "Historical Pool Exhaustion",
                "service": "payment-svc",
                "similarity_score": 4.5,
                "matched_signals": ["db/pool.py", "acquire_conn"],
                "failure_location": "db/pool.py:30",
                "triggering_condition": "High concurrency burst",
                "root_cause_hypothesis": "Small pool limit",
                "resolution_notes": "Increased max connections",
            }
        ],
        "timeline": [
            {
                "timestamp": "2026-10-04T12:00:00Z",
                "event_type": "INCIDENT_CREATED",
                "description": "Incident created with severity high.",
                "source": "incident",
                "actor": "system",
            },
            {
                "timestamp": "2026-10-04T12:10:00Z",
                "event_type": "EXECUTION_COMPLETED",
                "description": "Safe action execution completed successfully.",
                "source": "safe_action",
                "actor": "system",
            },
        ],
        "generated_at": "2026-10-04T12:20:00Z",
    }

    dto = IncidentReportDTO.from_dict(raw)
    assert dto.incident["incident_id"] == "inc-dto-1"
    assert dto.incident["service"] == "payment-svc"
    assert len(dto.timeline) == 2
    assert isinstance(dto.timeline[0], TimelineEventDTO)
    assert dto.timeline[0].event_type == "INCIDENT_CREATED"
    assert dto.timeline[1].event_type == "EXECUTION_COMPLETED"
    assert len(dto.similar_incidents) == 1
    assert isinstance(dto.similar_incidents[0], SimilarIncidentReportDTO)
    assert dto.similar_incidents[0].similarity_score == 4.5
    assert dto.generated_at is not None
    assert dto.generated_at.isoformat().startswith("2026-10-04T12:20:00")


def test_client_get_incident_report():
    """Verify SentinelOpsClient.get_incident_report issues correctly scoped GET request."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={
            "incident": {"incident_id": "inc-42", "project_id": "proj-alpha", "title": "Test Inc"},
            "detection_and_evidence": {"total_evidence_count": 0, "items": []},
            "investigation": None,
            "remediation": None,
            "human_decisions": [],
            "safe_actions": [],
            "notifications": [],
            "similar_incidents": [],
            "timeline": [],
            "generated_at": "2026-10-05T00:00:00Z",
        })

    transport = httpx.MockTransport(handler)
    client = SentinelOpsClient(base_url="http://testserver", timeout=5.0)
    client._client = httpx.Client(base_url="http://testserver", transport=transport)

    report = client.get_incident_report("inc-42", project_id="proj-alpha")
    assert captured["method"] == "GET"
    assert captured["path"] == "/incidents/inc-42/report"
    assert captured["params"] == {"project_id": "proj-alpha"}
    assert report is not None
    assert report.incident["incident_id"] == "inc-42"


def test_incidents_view_report_tab_structure(qapp):
    """Verify IncidentsView contains Report, Timeline, and Operational Memory tabs."""
    client = MagicMock(spec=SentinelOpsClient)
    runner = MagicMock(spec=TaskRunner)
    view = IncidentsView(client=client, task_runner=runner)

    tab_titles = [view.tabs.tabText(i) for i in range(view.tabs.count())]
    assert "Report" in tab_titles
    assert "Timeline" in tab_titles
    assert "Operational Memory" in tab_titles
    assert hasattr(view, "btn_copy_markdown")
    assert hasattr(view, "report_text")
    assert hasattr(view, "timeline_text")
    assert hasattr(view, "memory_text")


def test_incidents_view_renders_report_and_copies_markdown(qapp):
    """Verify report rendering and markdown clipboard copy formatting."""
    client = MagicMock(spec=SentinelOpsClient)
    runner = MagicMock(spec=TaskRunner)
    view = IncidentsView(client=client, task_runner=runner)

    # Set mock current incident
    view._selected_incident = IncidentDTO(
        id="inc-test",
        title="Database Connection Failure",
        summary="Pool timeout",
        severity="high",
        status="investigating",
        service="db-service",
        environment="prod",
        created_at="2026-10-04T10:00:00Z",
        updated_at="2026-10-04T10:05:00Z",
        project_id="proj-1",
    )

    sample_report = IncidentReportDTO.from_dict({
        "incident": {
            "incident_id": "inc-test",
            "project_id": "proj-1",
            "title": "Database Connection Failure",
            "summary": "Pool timeout",
            "severity": "high",
            "status": "investigating",
            "service": "db-service",
            "environment": "prod",
            "created_at": "2026-10-04T10:00:00Z",
            "updated_at": "2026-10-04T10:05:00Z",
        },
        "detection_and_evidence": {
            "total_evidence_count": 1,
            "items": [{"id": "ev-1", "type": "runtime_log", "source": "db.log", "timestamp": "2026-10-04T10:00:00Z", "level": "ERROR", "event": "timeout", "message": "Timed out after 5s"}],
        },
        "investigation": {
            "root_cause_hypothesis": "Connection pool starvation",
            "failure_location": "db/pool.py:10",
            "confidence": 0.95,
        },
        "remediation": {
            "remediation_id": "rem-1",
            "summary": "Increase pool connections",
            "branch_name": "remediate-pool",
        },
        "human_decisions": [],
        "safe_actions": [],
        "notifications": [],
        "similar_incidents": [
            {
                "incident_id": "inc-old-1",
                "project_id": "proj-1",
                "title": "Prior DB Starvation",
                "service": "db-service",
                "similarity_score": 5.0,
                "matched_signals": ["db/pool.py"],
                "failure_location": "db/pool.py:10",
                "triggering_condition": "burst",
                "root_cause_hypothesis": "low max conn",
                "resolution_notes": "Bump pool size to 50",
            }
        ],
        "timeline": [
            {
                "timestamp": "2026-10-04T10:00:00Z",
                "event_type": "INCIDENT_CREATED",
                "description": "Incident created.",
                "source": "incident",
                "actor": "system",
            }
        ],
        "generated_at": "2026-10-04T10:10:00Z",
    })

    view._render_report(sample_report)

    # Verify Report text contains core executive summary
    report_content = view.report_text.toPlainText()
    assert "Database Connection Failure" in report_content
    assert "Connection pool starvation" in report_content
    assert "Increase pool connections" in report_content

    # Verify Timeline contains item
    timeline_content = view.timeline_text.toPlainText()
    assert "Incident created." in timeline_content

    # Verify Operational Memory text contains similar incident
    memory_content = view.memory_text.toPlainText()
    assert "Prior DB Starvation" in memory_content
    assert "Bump pool size to 50" in memory_content

    # Verify clipboard copy method executes safely without error
    view._copy_report_markdown()
    clipboard = QApplication.clipboard()
    copied = clipboard.text()
    assert "Database Connection Failure" in copied
    assert "Connection pool starvation" in copied


def test_incidents_view_stale_response_discarded(qapp):
    """Verify generation token protects against stale asynchronous report responses."""
    client = MagicMock(spec=SentinelOpsClient)
    runner = MagicMock(spec=TaskRunner)
    view = IncidentsView(client=client, task_runner=runner)

    # Simulate generation 1
    view._current_generation = 1
    stale_generation = 1

    # User clicks another incident, bumping generation to 2
    view._current_generation = 2

    # Stale response arrives from generation 1
    old_report = IncidentReportDTO.from_dict({
        "incident": {"incident_id": "inc-old", "project_id": "proj-1", "title": "Old Incident"},
        "detection_and_evidence": {"total_evidence_count": 0, "items": []},
        "investigation": None,
        "remediation": None,
        "human_decisions": [],
        "safe_actions": [],
        "notifications": [],
        "similar_incidents": [],
        "timeline": [],
        "generated_at": "2026-10-05T00:00:00Z",
    })

    # When callback checks generation, it must discard
    if stale_generation == view._current_generation:
        view._render_report(old_report)

    # UI should not show old incident title
    assert "Old Incident" not in view.report_text.toPlainText()
