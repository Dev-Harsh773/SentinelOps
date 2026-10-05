"""Unit tests for desktop client safe actions methods and models."""

import pytest
import httpx

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QInputDialog, QLabel

from desktop.api.client import SentinelOpsClient
from desktop.api.models import SafeActionDTO, ActionAuditDTO


def test_safe_action_dto_from_dict():
    """Verify SafeActionDTO parsing from backend response dictionary."""
    data = {
        "action_id": "act-101",
        "project_id": "proj-1",
        "incident_id": "inc-1",
        "action_type": "test_connector",
        "target_type": "connector",
        "target_id": "conn-1",
        "parameters": {},
        "fingerprint": "abc123456789",
        "requested_by_claim": "operator:alice",
        "risk_level": "low",
        "policy_status": "allowed",
        "approval_status": "pending",
        "execution_status": "not_started",
        "created_at": "2026-10-03T12:00:00Z",
        "updated_at": "2026-10-03T12:00:00Z",
    }
    dto = SafeActionDTO.from_dict(data)
    assert dto.action_id == "act-101"
    assert dto.action_type == "test_connector"
    assert dto.target_id == "conn-1"
    assert dto.fingerprint == "abc123456789"
    assert dto.policy_status == "allowed"


def test_client_safe_actions_methods():
    """Verify SentinelOpsClient methods construct correct HTTP requests."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/actions" and request.method == "GET":
            return httpx.Response(200, json=[{
                "action_id": "act-1",
                "project_id": "proj-1",
                "action_type": "test_connector",
                "target_type": "connector",
                "target_id": "conn-1",
                "parameters": {},
                "fingerprint": "fp1",
                "requested_by_claim": "admin",
                "risk_level": "low",
                "policy_status": "allowed",
                "approval_status": "pending",
                "execution_status": "not_started",
            }])
        elif request.url.path == "/actions/propose" and request.method == "POST":
            return httpx.Response(201, json={
                "action_id": "act-new",
                "project_id": "proj-1",
                "action_type": "test_connector",
                "target_type": "connector",
                "target_id": "conn-1",
                "parameters": {},
                "fingerprint": "fp-new",
                "requested_by_claim": "admin",
                "risk_level": "low",
                "policy_status": "allowed",
                "approval_status": "pending",
                "execution_status": "not_started",
            })
        elif request.url.path == "/actions/act-1/approve" and request.method == "POST":
            return httpx.Response(200, json={
                "action_id": "act-1",
                "project_id": "proj-1",
                "action_type": "test_connector",
                "target_type": "connector",
                "target_id": "conn-1",
                "parameters": {},
                "fingerprint": "fp1",
                "requested_by_claim": "admin",
                "risk_level": "low",
                "policy_status": "allowed",
                "approval_status": "approved",
                "execution_status": "not_started",
            })
        elif request.url.path == "/actions/act-1/execute" and request.method == "POST":
            return httpx.Response(200, json={
                "action_id": "act-1",
                "project_id": "proj-1",
                "action_type": "test_connector",
                "target_type": "connector",
                "target_id": "conn-1",
                "parameters": {},
                "fingerprint": "fp1",
                "requested_by_claim": "admin",
                "risk_level": "low",
                "policy_status": "allowed",
                "approval_status": "approved",
                "execution_status": "succeeded",
            })
        elif request.url.path == "/actions/act-1/audit" and request.method == "GET":
            return httpx.Response(200, json=[{
                "audit_id": "aud-1",
                "action_id": "act-1",
                "event_type": "PROPOSED",
                "actor_claim": "admin",
                "previous_state": {},
                "new_state": {},
                "message": "Action proposed",
            }])
        return httpx.Response(404)

    client = SentinelOpsClient(transport=httpx.MockTransport(handler))

    # Test list_actions
    actions = client.list_actions(project_id="proj-1")
    assert len(actions) == 1
    assert actions[0].action_id == "act-1"

    # Test propose_action
    proposed = client.propose_action(
        project_id="proj-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        operator_claim="admin",
    )
    assert proposed.action_id == "act-new"

    # Test approve_action
    approved = client.approve_action("act-1", "admin")
    assert approved.approval_status == "approved"

    # Test execute_action
    executed = client.execute_action("act-1")
    assert executed.execution_status == "succeeded"

    # Test get_action_audit
    audits = client.get_action_audit("act-1")
    assert len(audits) == 1
    assert audits[0]["event_type"] == "PROPOSED"


# =====================================================================
# UI & Callback Lifecycle Tests
# =====================================================================

import os
import sys
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QApplication, QInputDialog, QLabel

from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.ui.views.incidents_view import IncidentsView
from desktop.api.models import IncidentDTO


@pytest.fixture(scope="session")
def qapp():
    """Ensure headless offscreen Qt application exists for tests."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture(autouse=True)
def reset_desktop_actions_state():
    """Ensure AppState singleton is reset for isolation across tests."""
    state = AppState()
    state._init_state()
    state.set_connection_status("online")
    yield
    state._init_state()
    for attr in [
        "connection_changed",
        "active_project_changed",
        "projects_updated",
        "incidents_updated",
        "notifications_updated",
        "connectors_updated",
        "knowledge_updated",
        "watcher_status_updated",
        "batch_unread_count_updated",
        "action_succeeded",
        "action_failed",
    ]:
        sig = getattr(app_signals, attr, None)
        if sig:
            try:
                sig.disconnect()
            except TypeError:
                pass


class SynchronousTaskRunner:
    """Synchronous test double for TaskRunner to avoid thread timing issues."""

    def __init__(self, max_threads: int = 4) -> None:
        pass

    def run(self, fn, on_success=None, on_error=None, *args, **kwargs):
        try:
            res = fn(*args, **kwargs)
            if on_success:
                on_success(res)
        except Exception as exc:
            if on_error:
                on_error(exc)

    def stop(self, timeout_ms: int = 2000) -> bool:
        return True


def test_safe_actions_execute_button_no_crash(qapp):
    """Verify Execute action does not crash with missing status_message signal and emits action_succeeded."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    client.list_actions.return_value = []
    updated_act = SafeActionDTO(
        action_id="act-1",
        project_id="p-1",
        incident_id="i-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        parameters={},
        fingerprint="fp1",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="approved",
        execution_status="succeeded",
    )
    client.execute_action.return_value = updated_act

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc = IncidentDTO(
        id="i-1",
        title="Test",
        summary="S",
        severity="high",
        status="open",
        service="auth",
        environment="prod",
        project_id="p-1",
    )
    view._selected_incident = inc

    initial_act = SafeActionDTO(
        action_id="act-1",
        project_id="p-1",
        incident_id="i-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        parameters={},
        fingerprint="fp1",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="approved",
        execution_status="not_started",
    )
    view._render_safe_actions([initial_act])

    succeeded_events = []
    app_signals.action_succeeded.connect(lambda title, msg: succeeded_events.append((title, msg)))

    # Execute action - MUST NOT CRASH
    view._execute_action("act-1")

    assert len(succeeded_events) >= 1
    assert succeeded_events[-1][0] == "Execution Completed"
    assert "SUCCEEDED" in succeeded_events[-1][1]
    client.execute_action.assert_called_once_with("act-1")


def test_safe_actions_approve_and_reject_path_no_crash(qapp, monkeypatch):
    """Verify Approve and Reject paths execute cleanly and notify via action_succeeded."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    client.list_actions.return_value = []
    approved_act = SafeActionDTO(
        action_id="act-1",
        project_id="p-1",
        incident_id="i-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        parameters={},
        fingerprint="fp1",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="approved",
        execution_status="not_started",
    )
    client.approve_action.return_value = approved_act

    rejected_act = SafeActionDTO(
        action_id="act-2",
        project_id="p-1",
        incident_id="i-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        parameters={},
        fingerprint="fp2",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="rejected",
        execution_status="aborted",
    )
    client.reject_action.return_value = rejected_act

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc = IncidentDTO(
        id="i-1",
        title="Test",
        summary="S",
        severity="high",
        status="open",
        service="auth",
        environment="prod",
        project_id="p-1",
    )
    view._selected_incident = inc

    succeeded_events = []
    app_signals.action_succeeded.connect(lambda title, msg: succeeded_events.append((title, msg)))

    # Mock QInputDialog.getText for Approve
    dialog_inputs = [("operator:admin", True), ("Good to go", True)]
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: dialog_inputs.pop(0))

    view._approve_action("act-1")
    assert any(title == "Action Approved" for title, _ in succeeded_events)
    client.approve_action.assert_called_once_with("act-1", "operator:admin", "Good to go")

    # Mock QInputDialog.getText for Reject
    dialog_inputs = [("operator:admin", True), ("Not safe", True)]
    view._reject_action("act-2")
    assert any(title == "Action Rejected" for title, _ in succeeded_events)
    client.reject_action.assert_called_once_with("act-2", "operator:admin", "Not safe")


def test_safe_actions_failure_callback_reports_error_without_crashing(qapp):
    """Verify failure during action execution reports error via action_failed without crashing."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    client.execute_action.side_effect = RuntimeError("Backend execution rejected: target missing")
    client.list_actions.return_value = []

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc = IncidentDTO(
        id="i-1",
        title="Test",
        summary="S",
        severity="high",
        status="open",
        service="auth",
        environment="prod",
        project_id="p-1",
    )
    view._selected_incident = inc

    failed_events = []
    app_signals.action_failed.connect(lambda title, msg: failed_events.append((title, msg)))

    view._execute_action("act-1")
    assert len(failed_events) >= 1
    assert failed_events[-1][0] == "Execution Error"
    assert "target missing" in failed_events[-1][1]


def test_missing_closed_incident_view_during_callback_does_not_crash(qapp):
    """Verify that if the view is deleted before worker completion, callback does not touch deleted Qt widgets."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    client.execute_action.return_value = SafeActionDTO(
        action_id="act-1",
        project_id="p-1",
        incident_id="i-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        parameters={},
        fingerprint="fp1",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="approved",
        execution_status="succeeded",
    )

    class DeletingTaskRunner:
        def __init__(self):
            self.view_ref = None

        def run(self, fn, on_success=None, on_error=None, *args, **kwargs):
            res = fn(*args, **kwargs)
            # Destroy the view before invoking on_success of the execute worker
            if self.view_ref and fn.__name__ == "worker":
                from PyQt6.sip import delete, isdeleted
                if not isdeleted(self.view_ref):
                    delete(self.view_ref)
            if on_success:
                on_success(res)

    runner = DeletingTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)
    runner.view_ref = view

    inc = IncidentDTO(
        id="i-1",
        title="Test",
        summary="S",
        severity="high",
        status="open",
        service="auth",
        environment="prod",
        project_id="p-1",
    )
    view._selected_incident = inc

    # Should not crash with RuntimeError despite view being deleted
    view._execute_action("act-1")


def test_rapid_navigate_away_while_execute_in_flight_no_crash(qapp):
    """Verify rapidly navigating away while execution is in flight does not crash or cross-contaminate UI."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    client.execute_action.return_value = SafeActionDTO(
        action_id="act-1",
        project_id="p-1",
        incident_id="i-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        parameters={},
        fingerprint="fp1",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="approved",
        execution_status="succeeded",
    )

    class DelayedTaskRunner:
        def __init__(self):
            self.saved_success = None
            self.saved_res = None

        def run(self, fn, on_success=None, on_error=None, *args, **kwargs):
            self.saved_res = fn(*args, **kwargs)
            self.saved_success = on_success

        def complete(self):
            if self.saved_success:
                self.saved_success(self.saved_res)

    runner = DelayedTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc1 = IncidentDTO(
        id="i-1",
        title="Test 1",
        summary="S",
        severity="high",
        status="open",
        service="auth",
        environment="prod",
        project_id="p-1",
    )
    inc2 = IncidentDTO(
        id="i-2",
        title="Test 2",
        summary="S",
        severity="low",
        status="open",
        service="pay",
        environment="prod",
        project_id="p-1",
    )
    view._selected_incident = inc1

    # Start execution on inc-1
    view._execute_action("act-1")

    # User rapidly navigates away to inc-2 before network response returns
    view._selected_incident = inc2

    # Network callback completes
    runner.complete()

    # Verify no crash, and actions_in_flight for act-1 was cleared
    assert "act-1" not in view._actions_in_flight


def test_reopen_incident_verifies_authoritative_server_state(qapp):
    """Verify that re-opening an incident fetches fresh authoritative safe actions from server."""
    state = AppState()
    state.set_connection_status("online")

    server_actions = [
        SafeActionDTO(
            action_id="act-server",
            project_id="p-1",
            incident_id="i-1",
            action_type="test_connector",
            target_type="connector",
            target_id="conn-1",
            parameters={},
            fingerprint="fp-srv",
            requested_by_claim="operator:charlie",
            risk_level="low",
            policy_status="allowed",
            approval_status="approved",
            execution_status="succeeded",
            execution_result={"ping": "ok"},
        )
    ]

    client = MagicMock(spec=SentinelOpsClient)
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    client.list_actions.return_value = server_actions

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc = IncidentDTO(
        id="i-1",
        title="Database Slowdown",
        summary="S",
        severity="high",
        status="open",
        service="db",
        environment="prod",
        project_id="p-1",
    )
    view._all_incidents = [inc]
    view._on_incidents_updated([inc], None)

    # Select row in table to open drawer
    view.table.selectRow(0)

    # Verify client.list_actions was called with incident_id="i-1"
    client.list_actions.assert_called_with(incident_id="i-1")

    # Verify cards rendered in actions_layout
    assert view.actions_layout.count() > 0


def test_external_new_action_appears_after_refresh(qapp):
    """Verify that an externally added safe action on the server appears in the UI after refresh."""
    state = AppState()
    state.set_connection_status("online")

    act_old = SafeActionDTO(
        action_id="act-old",
        project_id="p-1",
        incident_id="i-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        parameters={},
        fingerprint="fp-old",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="approved",
        execution_status="failed",
    )
    act_new = SafeActionDTO(
        action_id="act-new",
        project_id="p-1",
        incident_id="i-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-2",
        parameters={},
        fingerprint="fp-new",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="pending",
        execution_status="not_started",
    )

    client = MagicMock(spec=SentinelOpsClient)
    inc = IncidentDTO(
        id="i-1",
        title="Payment Latency",
        summary="Sum",
        severity="high",
        status="open",
        service="pay",
        environment="prod",
        project_id="p-1",
    )
    client.list_incidents.return_value = [inc]
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None

    # Initial query returns only old action
    client.list_actions.return_value = [act_old]

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)
    view._all_incidents = [inc]
    view._on_incidents_updated([inc], None)
    view.table.selectRow(0)

    # Verify initial card count
    assert view.actions_layout.count() > 0

    # Server state updates externally with 2 actions
    client.list_actions.return_value = [act_new, act_old]

    # Refresh
    view.refresh()

    # Verify actions were re-fetched and rendered
    client.list_actions.assert_called_with(incident_id="i-1")
    # Finding child widgets in actions_layout
    cards = [view.actions_layout.itemAt(i).widget() for i in range(view.actions_layout.count()) if view.actions_layout.itemAt(i) and view.actions_layout.itemAt(i).widget()]
    assert len(cards) >= 2


def test_external_new_action_appears_after_incident_reselection(qapp):
    """Verify clicking an already-selected incident row forces re-fetching of safe actions."""
    state = AppState()
    state.set_connection_status("online")

    act_1 = SafeActionDTO(
        action_id="act-1", project_id="p-1", incident_id="i-1", action_type="test_connector",
        target_type="connector", target_id="conn-1", parameters={}, fingerprint="fp-1",
        requested_by_claim="admin", risk_level="low", policy_status="allowed",
        approval_status="approved", execution_status="failed",
    )
    act_2 = SafeActionDTO(
        action_id="act-2", project_id="p-1", incident_id="i-1", action_type="test_connector",
        target_type="connector", target_id="conn-2", parameters={}, fingerprint="fp-2",
        requested_by_claim="admin", risk_level="low", policy_status="allowed",
        approval_status="pending", execution_status="not_started",
    )

    client = MagicMock(spec=SentinelOpsClient)
    inc = IncidentDTO(
        id="i-1", title="Payment Latency", summary="Sum", severity="high",
        status="open", service="pay", environment="prod", project_id="p-1",
    )
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    client.list_actions.return_value = [act_1]

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)
    view._all_incidents = [inc]
    view._on_incidents_updated([inc], None)
    view.table.selectRow(0)

    # Server updates externally
    client.list_actions.return_value = [act_2, act_1]

    # Re-click the cell
    view._on_cell_clicked(0, 2)

    cards = [view.actions_layout.itemAt(i).widget() for i in range(view.actions_layout.count()) if view.actions_layout.itemAt(i) and view.actions_layout.itemAt(i).widget()]
    assert len(cards) >= 2


def test_navigate_away_and_back_fetches_latest_actions(qapp):
    """Verify on_view_activated re-fetches latest safe actions when user returns to Incidents tab."""
    state = AppState()
    state.set_connection_status("online")

    act_1 = SafeActionDTO(
        action_id="act-1", project_id="p-1", incident_id="i-1", action_type="test_connector",
        target_type="connector", target_id="conn-1", parameters={}, fingerprint="fp-1",
        requested_by_claim="admin", risk_level="low", policy_status="allowed",
        approval_status="approved", execution_status="failed",
    )
    act_2 = SafeActionDTO(
        action_id="act-2", project_id="p-1", incident_id="i-1", action_type="test_connector",
        target_type="connector", target_id="conn-2", parameters={}, fingerprint="fp-2",
        requested_by_claim="admin", risk_level="low", policy_status="allowed",
        approval_status="pending", execution_status="not_started",
    )

    client = MagicMock(spec=SentinelOpsClient)
    inc = IncidentDTO(
        id="i-1", title="Payment Latency", summary="Sum", severity="high",
        status="open", service="pay", environment="prod", project_id="p-1",
    )
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    client.list_actions.return_value = [act_1]

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)
    view._all_incidents = [inc]
    view._on_incidents_updated([inc], None)
    view.table.selectRow(0)

    # Server updates
    client.list_actions.return_value = [act_2, act_1]

    # User returns to tab
    view.on_view_activated()

    cards = [view.actions_layout.itemAt(i).widget() for i in range(view.actions_layout.count()) if view.actions_layout.itemAt(i) and view.actions_layout.itemAt(i).widget()]
    assert len(cards) >= 2


def test_selected_incident_remains_selected_after_refresh(qapp):
    """Verify that Refresh preserves the currently selected incident and its highlighted table row."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    inc1 = IncidentDTO(id="i-1", title="Inc 1", summary="S1", severity="high", status="open", service="auth", environment="prod", project_id="p-1")
    inc2 = IncidentDTO(id="i-2", title="Inc 2", summary="S2", severity="low", status="open", service="pay", environment="prod", project_id="p-1")
    client.list_incidents.return_value = [inc1, inc2]
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    client.list_actions.return_value = []

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)
    view._all_incidents = [inc1, inc2]
    view._on_incidents_updated([inc1, inc2], None)

    # Select incident 2 (row 1)
    view.table.selectRow(1)
    assert view._selected_incident is not None
    assert view._selected_incident.id == "i-2"

    # Refresh
    view.refresh()

    # Incident 2 remains selected
    assert view._selected_incident is not None
    assert view._selected_incident.id == "i-2"
    selected_rows = view.table.selectionModel().selectedRows()
    assert len(selected_rows) == 1
    assert selected_rows[0].row() == 1


def test_stale_response_from_previous_incident_cannot_overwrite_current_incident(qapp):
    """Verify that if incident A's response returns after user has switched to incident B, A is discarded."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    act_a = SafeActionDTO(
        action_id="act-a", project_id="p-1", incident_id="i-A", action_type="test_connector",
        target_type="connector", target_id="conn-A", parameters={}, fingerprint="fp-A",
        requested_by_claim="admin", risk_level="low", policy_status="allowed",
        approval_status="pending", execution_status="not_started",
    )
    act_b = SafeActionDTO(
        action_id="act-b", project_id="p-1", incident_id="i-B", action_type="test_connector",
        target_type="connector", target_id="conn-B", parameters={}, fingerprint="fp-B",
        requested_by_claim="admin", risk_level="low", policy_status="allowed",
        approval_status="approved", execution_status="succeeded",
    )

    inc_a = IncidentDTO(id="i-A", title="Inc A", summary="SA", severity="high", status="open", service="auth", environment="prod", project_id="p-1")
    inc_b = IncidentDTO(id="i-B", title="Inc B", summary="SB", severity="low", status="open", service="pay", environment="prod", project_id="p-1")

    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None

    class QueueTaskRunner:
        def __init__(self):
            self.tasks = []

        def run(self, fn, on_success=None, on_error=None, *args, **kwargs):
            self.tasks.append((fn, on_success, on_error))

    runner = QueueTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)
    view._all_incidents = [inc_a, inc_b]
    view._on_incidents_updated([inc_a, inc_b], None)

    # 1. User selects Incident A
    client.list_actions.return_value = [act_a]
    view._selected_incident = inc_a
    view._render_incident_detail(inc_a)
    assert len(runner.tasks) == 1
    task_a = runner.tasks.pop(0)

    # 2. User rapidly switches to Incident B before A returns
    client.list_actions.return_value = [act_b]
    view._selected_incident = inc_b
    view._render_incident_detail(inc_b)
    assert len(runner.tasks) == 1
    task_b = runner.tasks.pop(0)

    # 3. Task A's network response finishes now
    fn_a, on_success_a, _ = task_a
    res_a = fn_a()
    on_success_a(res_a)

    # Should NOT have rendered act-a because selected incident is B
    # Actions layout should still be in loading state or empty for B
    labels = [view.actions_widget.findChildren(QLabel)[0].text()] if view.actions_widget.findChildren(QLabel) else []
    assert not any("ACT-A" in l.upper() for l in labels)

    # 4. Task B's network response finishes
    fn_b, on_success_b, _ = task_b
    res_b = fn_b()
    on_success_b(res_b)

    # Should render act-b
    assert view._selected_incident.id == "i-B"
    cards = [view.actions_layout.itemAt(i).widget() for i in range(view.actions_layout.count()) if view.actions_layout.itemAt(i) and view.actions_layout.itemAt(i).widget()]
    assert len(cards) >= 1


def test_refresh_button_signal_is_wired_and_invokes_current_view_refresh(qapp):
    """Verify that clicking the HeaderBar Refresh button invokes MainWindow._on_global_refresh and active view refresh."""
    from desktop.config import DesktopConfig
    from desktop.ui.main_window import MainWindow

    cfg = DesktopConfig()
    client = MagicMock(spec=SentinelOpsClient)
    client.list_projects.return_value = []
    client.get_health.return_value = {"status": "ok"}
    client.get_watcher_status.return_value = {"status": "running"}

    win = MainWindow(config=cfg, client=client)
    # Stop poller to prevent interference
    win.poller.stop()
    win.state.set_connection_status("online")

    # Switch to Incidents View
    win._on_navigation(1)
    assert win.stack.currentIndex() == 1

    # Mock refresh on incidents view
    win.incidents_view.refresh = MagicMock()
    win.poller.trigger_immediate_refresh = MagicMock()

    # Click Header Refresh button
    win.header.refresh_btn.click()

    win.poller.trigger_immediate_refresh.assert_called_once()
    win.incidents_view.refresh.assert_called_once()

    win.poller.stop()
    win.poller.wait(1000)
    win.task_runner.stop(1000)
    win.close()


def test_rapid_refresh_clicks_do_not_crash_or_duplicate_unsafe_work(qapp):
    """Verify that rapid clicks on Refresh button do not spawn concurrent duplicate workers."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    inc = IncidentDTO(id="i-1", title="Inc 1", summary="S1", severity="high", status="open", service="auth", environment="prod", project_id="p-1")
    client.list_incidents.return_value = [inc]
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    client.list_actions.return_value = []

    spawned_workers = []

    class CountingRunner:
        def run(self, fn, on_success=None, on_error=None, *args, **kwargs):
            spawned_workers.append(fn)

    runner = CountingRunner()
    view = IncidentsView(client=client, task_runner=runner)

    # First refresh starts
    view.refresh()
    assert len(spawned_workers) == 1
    assert view._is_refreshing is True

    # Immediate second and third clicks while first is in flight
    view.refresh()
    view.refresh()
    assert len(spawned_workers) == 1  # Blocked by _is_refreshing guard


def test_selected_incident_disappears_from_refreshed_list_clears_stale_detail(qapp):
    """Verify that when a refreshed authoritative incident list no longer contains the selected incident:

    - selected incident is cleared
    - stale detail pane (title, badges, meta, summary, evidence, investigation, remediation) is cleared
    - Safe Actions content is cleared with neutral empty state ("No incident selected.")
    - no stale action cards remain
    - table selection is cleared
    """
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc1 = IncidentDTO(
        id="inc-vanish-1",
        title="Vanishing Incident",
        summary="Transient incident that disappeared on restart",
        severity="high",
        status="open",
        service="payment-svc",
        environment="production",
        project_id="p-1",
    )
    act1 = SafeActionDTO(
        action_id="act-vanish-1",
        project_id="p-1",
        incident_id="inc-vanish-1",
        action_type="test_connector",
        target_type="connector",
        target_id="conn-1",
        parameters={},
        fingerprint="fp1",
        requested_by_claim="admin",
        risk_level="low",
        policy_status="allowed",
        approval_status="approved",
        execution_status="executing",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )

    # 1. Initially incident is present and selected
    view._all_incidents = [inc1]
    view._selected_incident = inc1
    view._render_incident_detail(inc1)
    view._render_safe_actions([act1])

    assert view.d_title.text() == "Vanishing Incident"
    assert view.d_sev_badge.isHidden() is False
    assert view.d_status_badge.isHidden() is False
    assert "Transient incident that disappeared on restart" in view.summary_text.toPlainText()
    cards = [view.actions_layout.itemAt(i).widget() for i in range(view.actions_layout.count()) if view.actions_layout.itemAt(i) and view.actions_layout.itemAt(i).widget()]
    assert len(cards) >= 1

    # 2. Refreshed authoritative list arrives empty (e.g. after backend restart with lost in-memory incident)
    view._on_incidents_updated([], None)

    # 3. Assert everything is cleared cleanly
    assert view._selected_incident is None
    assert view.d_title.text() == "Select an incident to view details"
    assert view.d_sev_badge.isHidden() is True
    assert view.d_status_badge.isHidden() is True
    assert view.d_meta_lbl.text() == "No incident selected"

    assert "No incident selected." in view.summary_text.toPlainText()
    assert "No incident selected." in view.evidence_text.toPlainText()
    assert "No incident selected." in view.investigation_text.toPlainText()
    assert "No incident selected." in view.remediation_text.toPlainText()

    # 4. Assert Safe Actions panel has neutral empty state ("No incident selected.") and zero action cards
    action_labels = [
        view.actions_layout.itemAt(i).widget().text()
        for i in range(view.actions_layout.count())
        if view.actions_layout.itemAt(i) and isinstance(view.actions_layout.itemAt(i).widget(), QLabel)
    ]
    assert any("No incident selected." in l for l in action_labels)
    # Ensure no action cards remain
    cards_remaining = [
        view.actions_layout.itemAt(i).widget()
        for i in range(view.actions_layout.count())
        if view.actions_layout.itemAt(i)
        and view.actions_layout.itemAt(i).widget()
        and view.actions_layout.itemAt(i).widget().property("class") == "Card"
    ]
    assert len(cards_remaining) == 0


def test_reconnect_with_persisted_incidents_recovers_list_and_selected_detail(qapp):
    """Verify that when backend returns persisted incidents after reconnect, list and selected detail reload normally."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    inc_persisted = IncidentDTO(
        id="inc-persisted-1",
        title="Persisted Incident",
        summary="Incident surviving restarts",
        severity="medium",
        status="investigating",
        service="order-svc",
        environment="staging",
        project_id="p-1",
    )
    client.list_incidents.return_value = [inc_persisted]
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    client.list_actions.return_value = []

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    # Start in cleared state
    view._clear_incident_detail()
    assert view._selected_incident is None
    assert view.d_title.text() == "Select an incident to view details"

    # Refreshed list arrives from backend
    view._on_incidents_updated([inc_persisted], None)
    assert len(view._all_incidents) == 1

    # Select the persisted incident
    view._selected_incident = inc_persisted
    view._render_incident_detail(inc_persisted)

    assert view._selected_incident.id == "inc-persisted-1"
    assert view.d_title.text() == "Persisted Incident"
    assert view.d_sev_badge.isHidden() is False
    assert view.d_status_badge.isHidden() is False
    assert "Incident surviving restarts" in view.summary_text.toHtml()


def test_rapid_navigation_and_reconnect_does_not_crash(qapp):
    """Verify that rapid project switching, offline/online toggles, and refreshes do not crash or leave inconsistent state."""
    state = AppState()
    client = MagicMock(spec=SentinelOpsClient)
    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc = IncidentDTO(
        id="i-rapid",
        title="Rapid Inc",
        summary="Rapid test",
        severity="low",
        status="open",
        service="svc",
        environment="test",
        project_id="p-1",
    )
    client.list_incidents.return_value = [inc]
    client.list_actions.return_value = []

    # Rapid events
    view._on_incidents_updated([inc], None)
    view._render_incident_detail(inc)
    view._on_project_changed("p-2")
    view._on_connection_changed("offline")
    view._on_connection_changed("online")
    view._on_incidents_updated([], None)
    view._on_project_changed("p-1")
    view._on_incidents_updated([inc], None)

    assert view._is_safe_to_update_ui() is True


def test_active_project_stage14_alpha_mixed_backend_response_only_stage14_alpha_rows_render(qapp):
    """Verify that when stage14-alpha is active, a mixed-project backend response strictly renders only stage14-alpha rows."""
    state = AppState()
    state.set_active_project("stage14-alpha")

    client = MagicMock(spec=SentinelOpsClient)
    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc_demo = IncidentDTO(
        id="inc-demo-1",
        title="Health Check Failed: demo-app",
        summary="Demo app down",
        severity="high",
        status="open",
        service="demo-app",
        environment="production",
        project_id="sentinelops-demo",
    )
    inc_stage14 = IncidentDTO(
        id="inc-s14-1",
        title="Stage 18 Persistence Final Verification",
        summary="Stage 14 verified",
        severity="medium",
        status="investigating",
        service="auth-service",
        environment="staging",
        project_id="stage14-alpha",
    )
    inc_other = IncidentDTO(
        id="inc-other-1",
        title="Other Project Issue",
        summary="Other summary",
        severity="low",
        status="open",
        service="other-service",
        environment="prod",
        project_id="other-project",
    )

    mixed_incidents = [inc_demo, inc_stage14, inc_other]

    # Directly pass mixed response to _on_incidents_updated
    view._on_incidents_updated(mixed_incidents, None)

    # Invariant: only stage14-alpha is kept in _all_incidents and table
    assert len(view._all_incidents) == 1
    assert view._all_incidents[0].id == "inc-s14-1"
    assert view.table.rowCount() == 1
    assert view.table.item(0, 2).text() == "Stage 18 Persistence Final Verification"
    assert view.table.item(0, 2).data(Qt.ItemDataRole.UserRole) == "inc-s14-1"


def test_manual_global_refresh_never_displays_another_project_incident(qapp):
    """Verify manual global Refresh never displays another project's incident even temporarily."""
    state = AppState()
    state.set_active_project("stage14-alpha")

    inc_demo = IncidentDTO(
        id="inc-demo-2",
        title="Health Check Failed: demo-app",
        summary="Demo issue",
        severity="critical",
        status="open",
        service="demo-svc",
        environment="prod",
        project_id="sentinelops-demo",
    )
    inc_stage14 = IncidentDTO(
        id="inc-s14-2",
        title="Stage 14 Auth Degraded",
        summary="Auth failure",
        severity="high",
        status="open",
        service="auth-svc",
        environment="prod",
        project_id="stage14-alpha",
    )

    client = MagicMock(spec=SentinelOpsClient)
    client.list_incidents.return_value = [inc_demo, inc_stage14]
    client.list_actions.return_value = []

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    # Trigger manual refresh
    view.refresh()

    # Must contain only stage14-alpha incident
    assert len(view._all_incidents) == 1
    assert view._all_incidents[0].id == "inc-s14-2"
    assert view.table.rowCount() == 1
    assert view.table.item(0, 2).text() == "Stage 14 Auth Degraded"


def test_background_polling_and_manual_refresh_use_same_project_filtering(qapp):
    """Verify background poller and manual refresh produce identical project-scoped rendering."""
    state = AppState()
    state.set_active_project("stage14-alpha")

    inc_demo = IncidentDTO(
        id="inc-demo-3",
        title="Demo Error",
        summary="Demo error",
        severity="low",
        status="open",
        service="demo",
        environment="test",
        project_id="sentinelops-demo",
    )
    inc_stage14 = IncidentDTO(
        id="inc-s14-3",
        title="Stage 14 Poller Incident",
        summary="Stage 14 poller summary",
        severity="medium",
        status="open",
        service="core",
        environment="stage",
        project_id="stage14-alpha",
    )
    all_data = [inc_demo, inc_stage14]

    client = MagicMock(spec=SentinelOpsClient)
    client.list_incidents.return_value = all_data
    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    # 1. Background poller path: calls state.set_incidents_from_all(all_data)
    state.set_incidents_from_all(all_data)
    assert len(view._all_incidents) == 1
    assert view._all_incidents[0].id == "inc-s14-3"
    assert view.table.rowCount() == 1
    assert view.table.item(0, 2).text() == "Stage 14 Poller Incident"

    # 2. Manual refresh path: calls view.refresh()
    view.refresh()
    assert len(view._all_incidents) == 1
    assert view._all_incidents[0].id == "inc-s14-3"
    assert view.table.rowCount() == 1
    assert view.table.item(0, 2).text() == "Stage 14 Poller Incident"


def test_delayed_response_from_previous_project_cannot_overwrite_current_project(qapp):
    """Verify delayed response from project A cannot overwrite project B's table when user switches."""
    state = AppState()
    state.set_active_project("project-A")

    class ControllableTaskRunner:
        def __init__(self):
            self.saved_fn = None
            self.saved_success = None

        def run(self, fn, on_success=None, on_error=None, *args, **kwargs):
            self.saved_fn = fn
            self.saved_success = on_success

        def flush(self):
            if self.saved_success and self.saved_fn:
                res = self.saved_fn()
                self.saved_success(res)
                self.saved_fn = None
                self.saved_success = None

    client = MagicMock(spec=SentinelOpsClient)
    runner = ControllableTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc_A = IncidentDTO(
        id="inc-A-1",
        title="Project A Incident",
        summary="Summary A",
        severity="high",
        status="open",
        service="svc-a",
        environment="prod",
        project_id="project-A",
    )

    # Project A initiates refresh
    client.list_incidents.return_value = [inc_A]
    view.refresh()

    # User switches to Project B before response returns
    state.set_active_project("project-B")
    view._on_project_changed("project-B")
    assert view.table.rowCount() == 0

    # Project A's delayed refresh response returns now!
    runner.flush()

    # Must NOT render Project A incident into Project B's table
    assert view.table.rowCount() == 0
    assert len(view._all_incidents) == 0


def test_rapid_project_switching_while_refresh_in_flight(qapp):
    """Verify rapid project switching with refreshes in flight does not crash or cross-contaminate."""
    state = AppState()
    client = MagicMock(spec=SentinelOpsClient)
    client.list_incidents.return_value = [
        IncidentDTO(id="ia", title="A", summary="A", severity="low", status="open", service="s", environment="e", project_id="p-A"),
        IncidentDTO(id="ib", title="B", summary="B", severity="high", status="open", service="s", environment="e", project_id="p-B"),
    ]
    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    for _ in range(5):
        state.set_active_project("p-A")
        view._on_project_changed("p-A")
        view.refresh()
        assert all(i.project_id == "p-A" for i in view._all_incidents)
        assert view.table.rowCount() == 1
        assert view.table.item(0, 2).text() == "A"

        state.set_active_project("p-B")
        view._on_project_changed("p-B")
        view.refresh()
        assert all(i.project_id == "p-B" for i in view._all_incidents)
        assert view.table.rowCount() == 1
        assert view.table.item(0, 2).text() == "B"


def test_reconnect_while_stage14_alpha_selected_only_stage14_alpha_renders(qapp):
    """Verify that when reconnecting after offline, only stage14-alpha incidents render."""
    state = AppState()
    state.set_active_project("stage14-alpha")
    state.set_connection_status("offline")

    client = MagicMock(spec=SentinelOpsClient)
    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    inc_demo = IncidentDTO(
        id="inc-demo-rec",
        title="Demo Reconnect",
        summary="Demo",
        severity="low",
        status="open",
        service="demo",
        environment="prod",
        project_id="sentinelops-demo",
    )
    inc_stage14 = IncidentDTO(
        id="inc-s14-rec",
        title="Stage 14 Reconnected",
        summary="Stage 14",
        severity="critical",
        status="open",
        service="core",
        environment="prod",
        project_id="stage14-alpha",
    )

    # Reconnected to backend
    state.set_connection_status("online")
    view._on_connection_changed("online")

    # Authoritative update arrives
    view._on_incidents_updated([inc_demo, inc_stage14], None)

    assert len(view._all_incidents) == 1
    assert view._all_incidents[0].id == "inc-s14-rec"
    assert view.table.rowCount() == 1
    assert view.table.item(0, 2).text() == "Stage 14 Reconnected"


def test_selected_stage14_alpha_incident_remains_selected_across_refresh(qapp):
    """Verify selected incident in stage14-alpha remains selected and re-renders across refresh."""
    state = AppState()
    state.set_active_project("stage14-alpha")

    inc = IncidentDTO(
        id="inc-s14-sel",
        title="Selected Incident",
        summary="Selected summary",
        severity="high",
        status="investigating",
        service="auth",
        environment="prod",
        project_id="stage14-alpha",
    )

    client = MagicMock(spec=SentinelOpsClient)
    client.list_incidents.return_value = [inc]
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    client.list_actions.return_value = []

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    # Populate and select
    view._on_incidents_updated([inc], None)
    view._selected_incident = inc
    view._restore_table_selection(inc.id)
    view._render_incident_detail(inc)

    assert view._selected_incident.id == "inc-s14-sel"

    # Refresh occurs
    updated_inc = IncidentDTO(
        id="inc-s14-sel",
        title="Selected Incident (Updated)",
        summary="Updated summary",
        severity="critical",
        status="investigating",
        service="auth",
        environment="prod",
        project_id="stage14-alpha",
    )
    client.list_incidents.return_value = [updated_inc]
    view.refresh()

    # Selection must be preserved and updated
    assert view._selected_incident is not None
    assert view._selected_incident.id == "inc-s14-sel"
    assert view._selected_incident.title == "Selected Incident (Updated)"
    assert view.d_title.text() == "Selected Incident (Updated)"


def test_selected_incident_removed_from_authoritative_scoped_result_clears_detail(qapp):
    """Verify that when the selected incident is removed from the authoritative result, details and Safe Actions clear."""
    state = AppState()
    state.set_active_project("stage14-alpha")

    inc_to_remove = IncidentDTO(
        id="inc-s14-remove",
        title="Will Be Removed",
        summary="To remove",
        severity="medium",
        status="open",
        service="auth",
        environment="prod",
        project_id="stage14-alpha",
    )
    inc_remaining = IncidentDTO(
        id="inc-s14-keep",
        title="Keep Me",
        summary="Remaining",
        severity="low",
        status="open",
        service="pay",
        environment="prod",
        project_id="stage14-alpha",
    )

    client = MagicMock(spec=SentinelOpsClient)
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    client.list_actions.return_value = []

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    # Initial state with both incidents, select inc_to_remove
    view._on_incidents_updated([inc_to_remove, inc_remaining], None)
    view._selected_incident = inc_to_remove
    view._render_incident_detail(inc_to_remove)
    assert view.d_title.text() == "Will Be Removed"

    # Authoritative response arrives with inc_to_remove absent
    view._on_incidents_updated([inc_remaining], None)

    # Detail must be completely cleared with neutral empty state
    assert view._selected_incident is None
    assert view.d_title.text() == "Select an incident to view details"
    assert view.d_sev_badge.isHidden() is True
    assert view.d_status_badge.isHidden() is True
    assert "No incident selected." in view.summary_text.toHtml()
    assert len(view._all_incidents) == 1
    assert view._all_incidents[0].id == "inc-s14-keep"


def test_repeated_refresh_clicks_do_not_flash_cross_project_rows(qapp):
    """Verify repeated rapid Refresh clicks never insert cross-project rows into the visible table."""
    state = AppState()
    state.set_active_project("stage14-alpha")

    inc_demo = IncidentDTO(
        id="inc-demo-flash",
        title="Health Check Failed: demo-app",
        summary="Demo",
        severity="high",
        status="open",
        service="demo",
        environment="prod",
        project_id="sentinelops-demo",
    )
    inc_stage14 = IncidentDTO(
        id="inc-s14-flash",
        title="Stage 18 Persistence Final Verification",
        summary="Stage 14",
        severity="medium",
        status="investigating",
        service="auth",
        environment="prod",
        project_id="stage14-alpha",
    )

    client = MagicMock(spec=SentinelOpsClient)
    client.list_incidents.return_value = [inc_demo, inc_stage14]
    client.list_actions.return_value = []

    runner = SynchronousTaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    # Rapid successive clicks
    for i in range(10):
        view.refresh()
        assert view.table.rowCount() == 1
        assert view.table.item(0, 2).text() == "Stage 18 Persistence Final Verification"
        # Confirm cross-project incident was never placed in table
        for row in range(view.table.rowCount()):
            item = view.table.item(row, 2)
            assert item.data(Qt.ItemDataRole.UserRole) != "inc-demo-flash"




