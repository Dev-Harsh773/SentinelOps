"""FastAPI endpoint integration tests for GET /incidents/{incident_id}/report."""

from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest

from app.actions.dependencies import close_action_store, set_custom_action_db_path
from app.agents.dependencies import close_investigation_repository, set_custom_investigation_db_path
from app.incidents.dependencies import close_incident_repository, get_incident_repository, set_custom_incident_db_path
from app.incidents.models import Incident, IncidentStatus, Severity
from app.main import app
from app.memory.dependencies import close_memory_repository, set_custom_memory_db_path
from app.notifications.dependencies import close_notification_store, set_custom_notification_db_path
from app.remediation.dependencies import close_remediation_repositories, set_custom_remediation_db_path
from app.telemetry.dependencies import close_evidence_repository, set_custom_evidence_db_path


@pytest.fixture(autouse=True)
def setup_api_dbs(tmp_path):
    test_db = str(tmp_path / "test_api_reports.db")
    set_custom_incident_db_path(test_db)
    set_custom_evidence_db_path(test_db)
    set_custom_investigation_db_path(test_db)
    set_custom_remediation_db_path(test_db)
    set_custom_action_db_path(test_db)
    set_custom_notification_db_path(test_db)
    set_custom_memory_db_path(test_db)

    yield

    close_remediation_repositories()
    close_investigation_repository()
    close_evidence_repository()
    close_memory_repository()
    close_action_store()
    close_notification_store()
    close_incident_repository()

    set_custom_incident_db_path(None)
    set_custom_evidence_db_path(None)
    set_custom_investigation_db_path(None)
    set_custom_remediation_db_path(None)
    set_custom_action_db_path(None)
    set_custom_notification_db_path(None)
    set_custom_memory_db_path(None)


def test_api_report_success():
    client = TestClient(app)
    now = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)
    inc = Incident(
        id="inc-api-1",
        title="API Incident",
        summary="API Summary",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="api-svc",
        environment="prod",
        created_at=now,
        updated_at=now,
        project_id="stage14-alpha",
    )
    get_incident_repository().create(inc)

    res = client.get("/incidents/inc-api-1/report", params={"project_id": "stage14-alpha"})
    assert res.status_code == 200
    data = res.json()
    assert data["incident"]["incident_id"] == "inc-api-1"
    assert data["incident"]["project_id"] == "stage14-alpha"
    assert "timeline" in data
    assert "generated_at" in data


def test_api_report_missing_project_id_returns_422():
    client = TestClient(app)
    res = client.get("/incidents/inc-api-1/report")
    assert res.status_code == 422


def test_api_report_cross_project_returns_404():
    client = TestClient(app)
    now = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)
    inc = Incident(
        id="inc-api-sec",
        title="Sec Incident",
        summary="Sec Summary",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="api-svc",
        environment="prod",
        created_at=now,
        updated_at=now,
        project_id="stage14-alpha",
    )
    get_incident_repository().create(inc)

    # Query with mismatched project_id returns 404 to avoid leaking existence
    res = client.get("/incidents/inc-api-sec/report", params={"project_id": "other-project"})
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_api_report_nonexistent_returns_404():
    client = TestClient(app)
    res = client.get("/incidents/nonexistent/report", params={"project_id": "stage14-alpha"})
    assert res.status_code == 404
