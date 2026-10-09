"""Headless tests for desktop PyQt6 UI components and views."""

import os
import sys
from datetime import datetime, timezone
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QHeaderView, QLabel

from desktop.api.client import SentinelOpsClient
from desktop.api.models import (
    ConnectorDTO,
    ConnectorHealthDTO,
    DetectedRouteDTO,
    IncidentDTO,
    NotificationDTO,
    ProjectDTO,
    ProjectKnowledgeDTO,
    WatcherStatusDTO,
)
from desktop.config import DesktopConfig
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.ui.components.header import HeaderBar
from desktop.ui.components.sidebar import SidebarRail
from desktop.ui.components.status_badge import StatusBadge
from desktop.ui.main_window import MainWindow
from desktop.ui.views.connectors_view import ConnectorsView
from desktop.ui.views.incidents_view import IncidentsView
from desktop.ui.views.knowledge_view import KnowledgeView
from desktop.ui.views.notifications_view import NotificationsView
from desktop.ui.views.overview_view import OverviewView
from desktop.ui.views.settings_view import SettingsView
from unittest.mock import MagicMock
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
def reset_desktop_views_state():
    """Ensure AppState singleton is reset for isolation across tests."""
    state = AppState()
    state._init_state()
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


def test_status_badge(qapp):
    badge = StatusBadge("critical", "critical")
    assert badge.text() == "CRITICAL"
    badge.set_value("resolved", "resolved")
    assert badge.text() == "RESOLVED"


def test_header_bar(qapp):
    header = HeaderBar()
    assert header.title_label.text() == "🛡️ SentinelOps Control Center"
    assert "CONNECTING" in header.connection_pill.text()

    header._update_connection_pill("online")
    assert "ONLINE" in header.connection_pill.text()

    header._update_connection_pill("offline")
    assert "OFFLINE" in header.connection_pill.text()


def test_sidebar_rail(qapp):
    sidebar = SidebarRail()
    assert len(sidebar.buttons) == 6
    assert "Overview" in sidebar.buttons[0].text()

    # Binding correction 2: batch unread label update
    sidebar._on_batch_unread_updated(3)
    assert "Feed (3 in batch)" in sidebar.buttons[2].text()

    sidebar._on_batch_unread_updated(0)
    assert sidebar.buttons[2].text() == "🔔 Feed"


def test_overview_view(qapp):
    view = OverviewView()
    now = datetime.now(timezone.utc)
    incidents = [
        IncidentDTO(id="i-1", title="Alpha Inc", summary="S1", severity="critical", status="open", service="auth", environment="prod", project_id="p-1"),
    ]
    view._on_incidents_updated(incidents, now)
    assert "1" in view.incidents_card.findChild(QLabel, "card_val").text()

    notifs = [
        NotificationDTO(notification_id="n-1", project_id="p-1", read_status="unread"),
    ]
    view._on_notifications_updated(notifs, now)
    assert "1" in view.feed_card.findChild(QLabel, "card_val").text()


def test_incidents_view_table_and_filtering(qapp):
    client = SentinelOpsClient()
    runner = TaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    incidents = [
        IncidentDTO(id="i-1", title="Payment Timeout", summary="Sum", severity="high", status="open", service="pay", environment="prod", project_id="p-1"),
        IncidentDTO(id="i-2", title="Auth Error", summary="Sum", severity="low", status="resolved", service="auth", environment="prod", project_id="p-1"),
    ]
    view._on_incidents_updated(incidents, datetime.now(timezone.utc))
    assert view.table.rowCount() == 2

    # Filter by severity
    view.sev_filter.setCurrentText("High")
    assert view.table.rowCount() == 1

    view.sev_filter.setCurrentText("All Severities")
    assert view.table.rowCount() == 2


def test_notifications_view_rendering(qapp):
    client = SentinelOpsClient()
    runner = TaskRunner()
    view = NotificationsView(client=client, task_runner=runner)

    notifs = [
        NotificationDTO(notification_id="n-1", project_id="p-1", title="Alert 1", message="M1", read_status="unread"),
        NotificationDTO(notification_id="n-2", project_id="p-1", title="Alert 2", message="M2", read_status="read"),
    ]
    view._on_notifications_updated(notifs, datetime.now(timezone.utc))
    assert "1 unread in active batch" in view.badge_count_label.text()


def test_connectors_view_rendering(qapp):
    client = SentinelOpsClient()
    runner = TaskRunner()
    view = ConnectorsView(client=client, task_runner=runner)

    conns = [
        ConnectorDTO(
            connector_id="c-1",
            project_id="p-1",
            name="Poller",
            connector_type="http_poller",
            health=ConnectorHealthDTO(connector_id="c-1", operational_status="healthy", target_status="healthy"),
        )
    ]
    view._on_connectors_updated(conns, datetime.now(timezone.utc))
    assert view.table.rowCount() == 1
    assert "Poller" in view.table.item(0, 0).text()


def test_connectors_view_auto_hydration_on_project_selection_and_activation(qapp):
    """Prove selecting/restoring a project automatically triggers connectors fetch and populates table without manual refresh."""
    state = AppState()
    state.set_connection_status("online")

    client = MagicMock(spec=SentinelOpsClient)
    sample_conns = [
        ConnectorDTO(
            connector_id="conn-stage21-gh",
            project_id="github-stage21",
            name="GitHub Webhook",
            connector_type="webhook",
            health=ConnectorHealthDTO(
                connector_id="conn-stage21-gh",
                operational_status="healthy",
                target_status="healthy",
                consecutive_operational_errors=0,
            ),
        )
    ]
    client.list_connectors.return_value = sample_conns

    # Synchronous task runner for deterministic headless testing
    runner = MagicMock()
    runner.run.side_effect = lambda worker, on_success=None, on_error=None: on_success(worker()) if on_success else None

    view = ConnectorsView(client=client, task_runner=runner)
    assert view.table.rowCount() == 0

    # Simulate user or startup selecting the project
    state.set_active_project("github-stage21")

    # Verify connectors were fetched and table immediately populated
    client.list_connectors.assert_called_with(project_id="github-stage21")
    assert view.table.rowCount() == 1
    assert "GitHub Webhook" in view.table.item(0, 0).text()
    assert "(1 registered)" in view.count_lbl.text()

    # Simulate navigating to Connectors view (on_view_activated)
    view.on_view_activated()
    assert view.table.rowCount() == 1
    assert "GitHub Webhook" in view.table.item(0, 0).text()



def test_knowledge_view_rendering(qapp):
    client = SentinelOpsClient()
    runner = TaskRunner()
    view = KnowledgeView(client=client, task_runner=runner)

    know = ProjectKnowledgeDTO(
        project_id="p-1",
        index_version="1.0",
        files_count=15,
        chunks_count=45,
        routes=[DetectedRouteDTO(method="GET", path="/orders", file_path="api.py", function_name="get_orders", start_line=10)],
        is_git=True,
        current_branch="main",
        current_head="abc1234",
    )
    view._on_knowledge_updated(know, datetime.now(timezone.utc))
    assert "Files: 15 | Chunks: 45" in view.files_lbl.text()
    assert "Git Branch: main" in view.branch_lbl.text()
    assert view.routes_table.rowCount() == 1


def test_settings_view_rendering(qapp, tmp_path):
    cfg_file = tmp_path / "settings.json"
    cfg = DesktopConfig(backend_url="http://127.0.0.1:8000")
    cfg.save(config_path=cfg_file)

    client = SentinelOpsClient()
    runner = TaskRunner()
    view = SettingsView(config=cfg, client=client, task_runner=runner)

    assert view.url_input.text() == "http://127.0.0.1:8000"


def test_main_window_assembly(qapp):
    cfg = DesktopConfig()
    client = MagicMock(spec=SentinelOpsClient)
    client.list_projects.return_value = []
    client.get_health.return_value = {"status": "ok"}
    client.get_watcher_status.return_value = {"status": "running"}
    win = MainWindow(config=cfg, client=client)
    assert win.windowTitle() == "SentinelOps Control Center"
    assert win.stack.count() == 6

    # Test navigation
    win._on_navigation(2)
    assert win.stack.currentIndex() == 2

    # Clean shutdown
    win.poller.stop()
    win.poller.wait(1000)
    win.close()


def test_incidents_view_lifecycle_buttons_state_awareness(qapp):
    from unittest.mock import MagicMock
    state = AppState()
    client = MagicMock(spec=SentinelOpsClient)
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    runner = TaskRunner()
    view = IncidentsView(client=client, task_runner=runner)
    state.set_connection_status("online")

    incidents = [
        IncidentDTO(id="i-open", title="Open Bug", summary="S", severity="high", status="open", service="auth", environment="prod", project_id="p-1"),
        IncidentDTO(id="i-inv", title="Inv Bug", summary="S", severity="high", status="investigating", service="auth", environment="prod", project_id="p-1"),
        IncidentDTO(id="i-res", title="Res Bug", summary="S", severity="high", status="resolved", service="auth", environment="prod", project_id="p-1"),
        IncidentDTO(id="i-close", title="Closed Bug", summary="S", severity="low", status="closed", service="auth", environment="prod", project_id="p-1"),
    ]
    view._on_incidents_updated(incidents, datetime.now(timezone.utc))

    # 1. OPEN: Investigate & Resolve shown and enabled; Close hidden
    view.table.selectRow(0)
    assert not view.btn_investigate.isHidden()
    assert view.btn_investigate.isEnabled() is True
    assert not view.btn_resolve.isHidden()
    assert view.btn_resolve.isEnabled() is True
    assert view.btn_close.isHidden()

    # 2. INVESTIGATING: Resolve shown and enabled; Investigate & Close hidden
    view.table.selectRow(1)
    assert view.btn_investigate.isHidden()
    assert not view.btn_resolve.isHidden()
    assert view.btn_resolve.isEnabled() is True
    assert view.btn_close.isHidden()

    # 3. RESOLVED: Close shown and enabled; Investigate & Resolve hidden
    view.table.selectRow(2)
    assert view.btn_investigate.isHidden()
    assert view.btn_resolve.isHidden()
    assert not view.btn_close.isHidden()
    assert view.btn_close.isEnabled() is True

    # 4. CLOSED: All lifecycle buttons hidden
    view.table.selectRow(3)
    assert view.btn_investigate.isHidden()
    assert view.btn_resolve.isHidden()
    assert view.btn_close.isHidden()


def test_offline_mode_disables_controls_and_pre_http_guards(qapp):
    from unittest.mock import MagicMock
    from PyQt6.QtWidgets import QFrame, QPushButton
    state = AppState()

    client = MagicMock(spec=SentinelOpsClient)
    client.list_incident_evidence.return_value = []
    client.get_incident_investigation.return_value = None
    client.get_incident_remediation.return_value = None
    runner = TaskRunner()

    header = HeaderBar()
    inc_view = IncidentsView(client=client, task_runner=runner)
    know_view = KnowledgeView(client=client, task_runner=runner)
    notif_view = NotificationsView(client=client, task_runner=runner)
    conn_view = ConnectorsView(client=client, task_runner=runner)

    state.set_connection_status("online")

    # Populate views
    incidents = [
        IncidentDTO(id="i-open", title="Open Bug", summary="S", severity="high", status="open", service="auth", environment="prod", project_id="p-1"),
    ]
    inc_view._on_incidents_updated(incidents, datetime.now(timezone.utc))
    inc_view.table.selectRow(0)

    notifs = [
        NotificationDTO(notification_id="n-1", project_id="p-1", title="A1", message="M1", read_status="unread", channel="webhook", delivery_status="failed"),
    ]
    notif_view._on_notifications_updated(notifs, datetime.now(timezone.utc))

    conns = [
        ConnectorDTO(
            connector_id="c-1",
            project_id="p-1",
            name="Poller",
            connector_type="http_poller",
            health=ConnectorHealthDTO(connector_id="c-1", operational_status="healthy", target_status="healthy"),
        )
    ]
    conn_view._on_connectors_updated(conns, datetime.now(timezone.utc))

    # In online state, verify initial enabled states
    assert header.refresh_btn.isEnabled() is True
    assert know_view.btn_reindex.isEnabled() is True
    assert notif_view.btn_mark_all.isEnabled() is True
    assert inc_view.btn_investigate.isEnabled() is True

    card_btns = notif_view.feed_widget.findChildren(QPushButton)
    assert len(card_btns) >= 2
    for b in card_btns:
        assert b.isEnabled() is True

    test_btn = conn_view.table.cellWidget(0, 6)
    assert test_btn.isEnabled() is True

    # Transition to OFFLINE
    state.set_connection_status("offline")

    assert header.refresh_btn.isEnabled() is False
    assert "Unavailable while offline" in header.refresh_btn.toolTip()

    assert know_view.btn_reindex.isEnabled() is False
    assert "Unavailable while offline" in know_view.btn_reindex.toolTip()

    assert notif_view.btn_mark_all.isEnabled() is False
    assert "Unavailable while offline" in notif_view.btn_mark_all.toolTip()

    card_btns_after = notif_view.feed_widget.findChildren(QPushButton)
    for b in card_btns_after:
        assert b.isEnabled() is False
        assert "Unavailable while offline" in b.toolTip()

    assert inc_view.btn_investigate.isEnabled() is False
    assert "Unavailable while offline" in inc_view.btn_investigate.toolTip()

    assert test_btn.isEnabled() is False
    assert "Unavailable while offline" in test_btn.toolTip()

    # Pre-HTTP guards test
    failed_actions = []
    def on_failed(title, msg):
        failed_actions.append((title, msg))

    app_signals.action_failed.connect(on_failed)

    inc_view._trigger_status_transition("investigating")
    assert len(failed_actions) == 1
    assert failed_actions[-1][0] == "Action Blocked"

    know_view._on_reindex_clicked()
    assert len(failed_actions) == 2
    assert failed_actions[-1][0] == "Action Blocked"

    notif_view._mark_read_server_confirmed("n-1")
    assert len(failed_actions) == 3
    assert failed_actions[-1][0] == "Action Blocked"

    notif_view._retry_server_confirmed("n-1")
    assert len(failed_actions) == 4
    assert failed_actions[-1][0] == "Action Blocked"

    notif_view._on_mark_all_read_clicked()
    assert len(failed_actions) == 5
    assert failed_actions[-1][0] == "Action Blocked"

    conn_view._test_connector("c-1")
    assert len(failed_actions) == 6
    assert failed_actions[-1][0] == "Action Blocked"

    # Transition back to ONLINE
    state.set_connection_status("online")

    assert header.refresh_btn.isEnabled() is True
    assert know_view.btn_reindex.isEnabled() is True
    assert notif_view.btn_mark_all.isEnabled() is True
    assert inc_view.btn_investigate.isEnabled() is True
    assert test_btn.isEnabled() is True


def test_ui_proportions_and_tooltips(qapp):
    header = HeaderBar()
    assert header.project_combo.minimumWidth() >= 320

    projects = [
        ProjectDTO(project_id="p-1", name="Alpha Project Long Name To Prevent Clipping", workspace_path="/workspace/alpha", status="ready"),
        ProjectDTO(project_id="p-2", name="Beta Project", workspace_path="/workspace/beta", status="ready"),
    ]
    header._on_projects_updated(projects)
    assert header.project_combo.count() == 2
    assert "Alpha Project Long Name To Prevent Clipping" in header.project_combo.itemData(0, Qt.ItemDataRole.ToolTipRole)
    assert "Alpha Project Long Name To Prevent Clipping" in header.project_combo.toolTip()

    client = SentinelOpsClient()
    runner = TaskRunner()
    view = IncidentsView(client=client, task_runner=runner)

    header_view = view.table.horizontalHeader()
    assert header_view.sectionSize(0) == 85   # Sev
    assert header_view.sectionSize(1) == 115  # Status
    assert header_view.sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch  # Title
    assert header_view.sectionSize(3) == 110  # Service
    assert header_view.sectionSize(4) == 75   # Env
    assert header_view.sectionSize(5) == 130  # Created
