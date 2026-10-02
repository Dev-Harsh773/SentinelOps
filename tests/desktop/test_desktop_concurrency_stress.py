"""Concurrency and lifecycle stress tests for SentinelOps desktop client.

Validates that any combination of navigation, background polling/refresh, project switching,
and concurrent user actions never accesses deleted Qt widgets or raises RuntimeError.
"""

import os
import sys
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPushButton

from desktop.api.client import SentinelOpsClient
from desktop.api.models import (
    ConnectorDTO,
    ConnectorHealthDTO,
    EvidenceDTO,
    IncidentDTO,
    NotificationDTO,
    ProjectDTO,
    ProjectKnowledgeDTO,
)
from desktop.config import DesktopConfig
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.ui.main_window import MainWindow
from desktop.workers.task_runner import TaskRunner


@pytest.fixture(scope="session")
def qapp():
    """Ensure headless offscreen Qt application exists."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture(autouse=True)
def reset_app_state():
    """Reset AppState singleton before and after each test."""
    state = AppState()
    state._init_state()
    state.set_connection_status("online")
    yield state
    state._init_state()


def test_stress_connector_test_in_flight_navigation_and_refresh(qapp, reset_app_state):
    """Scenario 1: Connector Test in flight + rapid navigation + background table refresh."""
    state = reset_app_state
    mock_client = MagicMock(spec=SentinelOpsClient)
    test_started = threading.Event()
    test_proceed = threading.Event()

    def delayed_test(connector_id):
        test_started.set()
        test_proceed.wait(timeout=5.0)
        return {"status": "healthy", "latency_ms": 12.5}

    mock_client.test_connector.side_effect = delayed_test
    cfg = DesktopConfig()
    win = MainWindow(config=cfg, client=mock_client)
    win.poller.stop()  # Control refresh cycles manually

    # Populate project and connectors
    conns = [
        ConnectorDTO(
            connector_id="conn-101",
            project_id="p-1",
            name="Production Poller",
            connector_type="http_poller",
            health=ConnectorHealthDTO(connector_id="conn-101", operational_status="healthy", target_status="healthy"),
        ),
        ConnectorDTO(
            connector_id="conn-102",
            project_id="p-1",
            name="Staging Poller",
            connector_type="http_poller",
            health=ConnectorHealthDTO(connector_id="conn-102", operational_status="healthy", target_status="healthy"),
        ),
    ]
    win.connectors_view._on_connectors_updated(conns, datetime.now(timezone.utc))

    # Navigate to ConnectorsView (index 3)
    win._on_navigation(3)
    qapp.processEvents()

    # Trigger connector test on conn-101
    win.connectors_view._test_connector("conn-101")
    assert test_started.wait(timeout=2.0)

    # In flight: verify duplicate click is guarded
    win.connectors_view._test_connector("conn-101")

    # While in flight: rapidly navigate across all views
    for idx in [0, 1, 2, 4, 5, 3, 0, 3]:
        win._on_navigation(idx)
        qapp.processEvents()

    # While in flight: simulate multiple background poller updates / table rebuilds
    for iteration in range(3):
        win.connectors_view._on_connectors_updated(conns, datetime.now(timezone.utc))
        qapp.processEvents()

    # Allow worker to complete
    test_proceed.set()
    win.task_runner.stop(timeout_ms=2000)
    qapp.processEvents()

    # Verify no exception was raised and conn-101 test button is cleanly re-enabled
    row_btn = win.connectors_view.table.cellWidget(0, 6)
    assert row_btn is not None
    assert row_btn.isEnabled() is True
    assert row_btn.text() == "Test"
    assert "conn-101" not in win.connectors_view._testing_connector_ids

    win.close()


def test_stress_reindex_in_flight_navigation_and_project_switch(qapp, reset_app_state, monkeypatch):
    """Scenario 2: Workspace reindexing in flight + rapid navigation + project switching."""
    state = reset_app_state
    state.set_projects([
        ProjectDTO(project_id="p-1", name="Alpha", workspace_path="/w/alpha", status="ready"),
        ProjectDTO(project_id="p-2", name="Beta", workspace_path="/w/beta", status="ready"),
    ])
    state.set_active_project("p-1")

    mock_client = MagicMock(spec=SentinelOpsClient)
    reindex_started = threading.Event()
    reindex_proceed = threading.Event()

    def delayed_reindex(project_id):
        reindex_started.set()
        reindex_proceed.wait(timeout=5.0)
        return ProjectKnowledgeDTO(
            project_id=project_id,
            index_version="2.0",
            files_count=42,
            chunks_count=128,
            routes=[],
            is_git=True,
            current_branch="main",
            current_head="abc1234",
            indexed_at=datetime.now(timezone.utc),
        )

    mock_client.reindex_project.side_effect = delayed_reindex
    mock_client.get_project_knowledge.return_value = ProjectKnowledgeDTO(
        project_id="p-1",
        index_version="1.0",
        files_count=10,
        chunks_count=20,
        routes=[],
        is_git=False,
    )

    cfg = DesktopConfig()
    win = MainWindow(config=cfg, client=mock_client)
    win.poller.stop()

    # Navigate to KnowledgeView (index 4)
    win._on_navigation(4)
    qapp.processEvents()

    # Bypass confirm dialog for automated stress test
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    win.knowledge_view._on_reindex_clicked()
    assert reindex_started.wait(timeout=2.0)

    # In flight: verify duplicate reindex click is guarded
    win.knowledge_view._on_reindex_clicked()
    assert "p-1" in win.knowledge_view._reindexing_projects

    # While in flight: switch active project to p-2
    state.set_active_project("p-2")
    qapp.processEvents()

    # Knowledge button for p-2 must NOT be disabled by p-1's in-flight reindex
    assert win.knowledge_view.btn_reindex.isEnabled() is True
    assert win.knowledge_view.btn_reindex.text() == "↻ Reindex Workspace"

    # Rapid navigation while reindexing
    for idx in [0, 1, 2, 3, 5, 4]:
        win._on_navigation(idx)
        qapp.processEvents()

    # Switch back to p-1
    state.set_active_project("p-1")
    qapp.processEvents()
    assert win.knowledge_view.btn_reindex.isEnabled() is False
    assert win.knowledge_view.btn_reindex.text() == "Reindexing..."

    # Complete reindex
    reindex_proceed.set()
    win.task_runner.stop(timeout_ms=2000)
    qapp.processEvents()

    assert win.knowledge_view.btn_reindex.isEnabled() is True
    assert win.knowledge_view.btn_reindex.text() == "↻ Reindex Workspace"
    assert "p-1" not in win.knowledge_view._reindexing_projects

    win.close()


def test_stress_notification_mark_read_retry_in_flight_feed_rebuild(qapp, reset_app_state):
    """Scenario 3: Notification Mark Read & Retry in flight + rapid feed rebuilds and filter toggling."""
    state = reset_app_state
    mock_client = MagicMock(spec=SentinelOpsClient)

    read_started = threading.Event()
    read_proceed = threading.Event()
    retry_started = threading.Event()
    retry_proceed = threading.Event()

    def delayed_mark_read(notif_id):
        read_started.set()
        read_proceed.wait(timeout=5.0)
        return NotificationDTO(
            notification_id=notif_id,
            project_id="p-1",
            title="Alert Read",
            message="Msg",
            read_status="read",
            channel="in_app",
            delivery_status="delivered",
        )

    def delayed_retry(notif_id):
        retry_started.set()
        retry_proceed.wait(timeout=5.0)
        return NotificationDTO(
            notification_id=notif_id,
            project_id="p-1",
            title="Alert Retried",
            message="Msg",
            read_status="unread",
            channel="webhook",
            delivery_status="pending",
        )

    mock_client.mark_notification_read.side_effect = delayed_mark_read
    mock_client.retry_notification.side_effect = delayed_retry

    cfg = DesktopConfig()
    win = MainWindow(config=cfg, client=mock_client)
    win.poller.stop()

    notifs = [
        NotificationDTO(notification_id="n-101", project_id="p-1", title="N1", message="M1", read_status="unread", channel="in_app", delivery_status="delivered"),
        NotificationDTO(notification_id="n-102", project_id="p-1", title="N2", message="M2", read_status="unread", channel="webhook", delivery_status="failed"),
    ]
    win.notifications_view._on_notifications_updated(notifs, datetime.now(timezone.utc))

    win._on_navigation(2)
    qapp.processEvents()

    # Trigger both mark-read on n-101 and retry on n-102
    win.notifications_view._mark_read_server_confirmed("n-101")
    win.notifications_view._retry_server_confirmed("n-102")

    assert read_started.wait(timeout=2.0)
    assert retry_started.wait(timeout=2.0)

    # In flight: verify duplicate triggers are safely ignored
    win.notifications_view._mark_read_server_confirmed("n-101")
    win.notifications_view._retry_server_confirmed("n-102")

    # While in flight: repeatedly rebuild feed and toggle filters (destroys and recreates card widgets)
    for _ in range(4):
        win.notifications_view.btn_unread.setChecked(True)
        win.notifications_view._on_filter_changed()
        qapp.processEvents()

        win.notifications_view._on_notifications_updated(notifs, datetime.now(timezone.utc))
        qapp.processEvents()

        win.notifications_view.btn_all.setChecked(True)
        win.notifications_view._on_filter_changed()
        qapp.processEvents()

    # Navigate away and back
    win._on_navigation(0)
    qapp.processEvents()
    win._on_navigation(2)
    qapp.processEvents()

    # Release workers
    read_proceed.set()
    retry_proceed.set()
    win.task_runner.stop(timeout_ms=2000)
    qapp.processEvents()

    assert "n-101" not in win.notifications_view._in_flight_reads
    assert "n-102" not in win.notifications_view._in_flight_retries

    win.close()


def test_stress_incident_status_update_in_flight_project_and_view_switch(qapp, reset_app_state):
    """Scenario 4: Incident status transition in flight + incident/project switching."""
    state = reset_app_state
    mock_client = MagicMock(spec=SentinelOpsClient)

    transition_started = threading.Event()
    transition_proceed = threading.Event()

    def delayed_transition(inc_id, status):
        transition_started.set()
        transition_proceed.wait(timeout=5.0)
        return IncidentDTO(
            id=inc_id,
            title="Inc Title",
            summary="Inc Summary",
            severity="critical",
            status=status,
            service="payments",
            environment="production",
            project_id="p-1",
        )

    mock_client.update_incident_status.side_effect = delayed_transition
    mock_client.list_incident_evidence.return_value = [
        EvidenceDTO(evidence_id="e-1", incident_id="i-1", signal_type="error", log_level="ERROR", message="Timeout", source_file="pay.py")
    ]
    mock_client.get_incident_investigation.return_value = None
    mock_client.get_incident_remediation.return_value = None

    cfg = DesktopConfig()
    win = MainWindow(config=cfg, client=mock_client)
    win.poller.stop()

    incidents_p1 = [
        IncidentDTO(id="i-1", title="Payment Outage", summary="Sum", severity="critical", status="open", service="pay", environment="prod", project_id="p-1"),
        IncidentDTO(id="i-2", title="Auth Latency", summary="Sum", severity="medium", status="investigating", service="auth", environment="prod", project_id="p-1"),
    ]
    state.set_projects([
        ProjectDTO(project_id="p-1", name="P1", workspace_path="/p1", status="ready"),
        ProjectDTO(project_id="p-2", name="P2", workspace_path="/p2", status="ready"),
    ])
    state.set_active_project("p-1")
    win.incidents_view._on_incidents_updated(incidents_p1, datetime.now(timezone.utc))

    win._on_navigation(1)
    win.incidents_view.table.selectRow(0)  # Select i-1
    qapp.processEvents()

    # Trigger status transition to investigating
    win.incidents_view._trigger_status_transition("investigating")
    assert transition_started.wait(timeout=2.0)

    # In flight: rapidly switch selection to i-2
    win.incidents_view.table.selectRow(1)
    qapp.processEvents()

    # In flight: rapidly switch active project to p-2
    state.set_active_project("p-2")
    qapp.processEvents()

    # In flight: navigate to Overview then back to Incidents
    win._on_navigation(0)
    qapp.processEvents()
    win._on_navigation(1)
    qapp.processEvents()

    # Complete i-1 transition worker
    transition_proceed.set()
    win.task_runner.stop(timeout_ms=2000)
    qapp.processEvents()

    # Verify no RuntimeError was raised and i-1 transition does not overwrite p-2 view
    assert "i-1" not in win.incidents_view._transitioning_incident_ids

    # Switch back to p-1: i-1 must reflect updated status in p-1 list
    state.set_active_project("p-1")
    win.incidents_view._on_incidents_updated(
        [
            IncidentDTO(id="i-1", title="Payment Outage", summary="Sum", severity="critical", status="investigating", service="pay", environment="prod", project_id="p-1"),
        ],
        datetime.now(timezone.utc),
    )
    qapp.processEvents()

    win.incidents_view.table.selectRow(0)
    qapp.processEvents()
    assert win.incidents_view._selected_incident.status == "investigating"
    assert win.incidents_view.btn_investigate.isHidden()
    assert not win.incidents_view.btn_resolve.isHidden()

    win.close()


def test_stress_settings_connection_test_in_flight_navigation(qapp, reset_app_state):
    """Scenario 5: Settings live connection test in flight + rapid tab navigation."""
    state = reset_app_state
    mock_client = MagicMock(spec=SentinelOpsClient)

    test_started = threading.Event()
    test_proceed = threading.Event()

    def delayed_health():
        test_started.set()
        test_proceed.wait(timeout=5.0)
        return {"status": "ok", "service": "sentinelops-backend"}

    cfg = DesktopConfig(backend_url="http://127.0.0.1:8000")
    win = MainWindow(config=cfg, client=mock_client)
    win.poller.stop()

    win._on_navigation(5)
    qapp.processEvents()

    # Inject mock health check client
    orig_client_cls = sys.modules["desktop.ui.views.settings_view"].SentinelOpsClient
    mock_temp_client = MagicMock()
    mock_temp_client.get_health.side_effect = delayed_health
    sys.modules["desktop.ui.views.settings_view"].SentinelOpsClient = lambda **kw: mock_temp_client

    try:
        win.settings_view._test_connection()
        assert test_started.wait(timeout=2.0)

        # In flight: verify duplicate click is guarded
        win.settings_view._test_connection()
        assert win.settings_view._test_in_flight is True
        assert win.settings_view.btn_test.isEnabled() is False

        # While in flight: rapidly cycle through all stack indexes multiple times
        for _ in range(2):
            for idx in range(6):
                win._on_navigation(idx)
                qapp.processEvents()

        # Complete test
        test_proceed.set()
        win.task_runner.stop(timeout_ms=2000)
        qapp.processEvents()

        # Return to settings view
        win._on_navigation(5)
        qapp.processEvents()
        assert win.settings_view.btn_test.isEnabled() is True
        assert win.settings_view.btn_test.text() == "Test Live Connection"
        assert win.settings_view._test_in_flight is False
    finally:
        sys.modules["desktop.ui.views.settings_view"].SentinelOpsClient = orig_client_cls
        win.close()


def test_stress_multiple_unrelated_async_operations_overlapping(qapp, reset_app_state, monkeypatch):
    """Scenario 6: Multiple unrelated async operations running simultaneously across views."""
    state = reset_app_state
    state.set_projects([
        ProjectDTO(project_id="p-1", name="Alpha", workspace_path="/w/alpha", status="ready"),
    ])
    state.set_active_project("p-1")

    all_proceed = threading.Event()

    mock_client = MagicMock(spec=SentinelOpsClient)
    mock_client.test_connector.side_effect = lambda cid: (all_proceed.wait(5.0), {"status": "healthy", "latency_ms": 10})[1]
    mock_client.reindex_project.side_effect = lambda pid: (
        all_proceed.wait(5.0),
        ProjectKnowledgeDTO(project_id=pid, index_version="2.0", files_count=10, chunks_count=20, routes=[], is_git=False),
    )[1]
    mock_client.mark_notification_read.side_effect = lambda nid: (
        all_proceed.wait(5.0),
        NotificationDTO(notification_id=nid, project_id="p-1", title="T", message="M", read_status="read"),
    )[1]
    mock_client.retry_notification.side_effect = lambda nid: (
        all_proceed.wait(5.0),
        NotificationDTO(notification_id=nid, project_id="p-1", title="T", message="M", read_status="unread", channel="webhook", delivery_status="pending"),
    )[1]
    mock_client.update_incident_status.side_effect = lambda iid, s: (
        all_proceed.wait(5.0),
        IncidentDTO(id=iid, title="T", summary="S", severity="high", status=s, service="srv", environment="env", project_id="p-1"),
    )[1]
    mock_client.list_incident_evidence.return_value = []
    mock_client.get_incident_investigation.return_value = None
    mock_client.get_incident_remediation.return_value = None

    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    cfg = DesktopConfig()
    win = MainWindow(config=cfg, client=mock_client)
    win.poller.stop()

    # Populate initial domain entities across views
    win.connectors_view._on_connectors_updated(
        [ConnectorDTO(connector_id="c-1", project_id="p-1", name="C1", connector_type="poller")],
        datetime.now(timezone.utc),
    )
    win.notifications_view._on_notifications_updated(
        [
            NotificationDTO(notification_id="n-1", project_id="p-1", title="T1", message="M1", read_status="unread", channel="in_app"),
            NotificationDTO(notification_id="n-2", project_id="p-1", title="T2", message="M2", read_status="unread", channel="webhook", delivery_status="failed"),
        ],
        datetime.now(timezone.utc),
    )
    win.incidents_view._on_incidents_updated(
        [IncidentDTO(id="i-1", title="T1", summary="S1", severity="high", status="open", service="auth", environment="prod", project_id="p-1")],
        datetime.now(timezone.utc),
    )
    win.incidents_view.table.selectRow(0)
    qapp.processEvents()

    # Launch 5 concurrent operations across different views
    win.connectors_view._test_connector("c-1")
    win.knowledge_view._on_reindex_clicked()
    win.notifications_view._mark_read_server_confirmed("n-1")
    win.notifications_view._retry_server_confirmed("n-2")
    win.incidents_view._trigger_status_transition("investigating")

    # While all 5 operations are overlapping:
    # Rapidly toggle connections, navigate, and emit poller signals
    for iteration in range(5):
        win._on_navigation(iteration % 6)
        qapp.processEvents()
        app_signals.connection_changed.emit("offline" if iteration % 2 == 1 else "online")
        qapp.processEvents()

    # Release all concurrent background workers
    all_proceed.set()
    win.task_runner.stop(timeout_ms=3000)
    qapp.processEvents()

    # Restore online state and verify views remain consistent without crashes
    state.set_connection_status("online")
    qapp.processEvents()

    assert len(win.connectors_view._testing_connector_ids) == 0
    assert len(win.knowledge_view._reindexing_projects) == 0
    assert len(win.notifications_view._in_flight_reads) == 0
    assert len(win.notifications_view._in_flight_retries) == 0
    assert len(win.incidents_view._transitioning_incident_ids) == 0

    win.close()
