"""Registered connectors monitoring and diagnostic view."""

from datetime import datetime, timezone
from typing import List
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.api.client import SentinelOpsClient
from desktop.api.models import ConnectorDTO
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.ui.components.status_badge import StatusBadge
from desktop.workers.task_runner import TaskRunner


class ConnectorsView(QWidget):
    """View displaying registered telemetry & deployment connectors and health status."""

    def __init__(self, client: SentinelOpsClient, task_runner: TaskRunner, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.task_runner = task_runner
        self.state = AppState()
        self._testing_connector_ids: set[str] = set()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # Header
        header_row = QHBoxLayout()
        self.title_lbl = QLabel("Connectors", self)
        self.title_lbl.setStyleSheet("font-size: 20px; font-weight: 700; color: #F8FAFC;")
        header_row.addWidget(self.title_lbl)

        self.count_lbl = QLabel("(0 connectors)", self)
        self.count_lbl.setStyleSheet("color: #94A3B8; font-size: 13px;")
        header_row.addWidget(self.count_lbl)
        header_row.addStretch()

        main_layout.addLayout(header_row)

        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Name",
            "Type",
            "Operational",
            "Target Status",
            "Errors",
            "Last Poll (UTC)",
            "Actions",
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        main_layout.addWidget(self.table)

        # Signals
        app_signals.connectors_updated.connect(self._on_connectors_updated)
        app_signals.connection_changed.connect(self._on_connection_changed)
        app_signals.active_project_changed.connect(self._on_project_changed)

        # Hydrate initial view state if active project is already selected
        if self.state.active_project_id:
            self._on_project_changed(self.state.active_project_id)

    def _update_test_button_for_row(self, row: int, connector_id: str) -> None:
        """Update test button presentation for a specific table row from state."""
        widget = self.table.cellWidget(row, 6)
        if not isinstance(widget, QPushButton):
            return

        is_in_flight = connector_id in self._testing_connector_ids
        is_online = self.state.is_online()

        if is_in_flight:
            widget.setEnabled(False)
            widget.setText("Pinging...")
            widget.setToolTip("Diagnostic ping in progress...")
        else:
            widget.setEnabled(is_online)
            widget.setText("Test")
            widget.setToolTip("" if is_online else "Unavailable while offline")

    def _sync_test_button_for_connector(self, connector_id: str) -> None:
        """Locate current table row for connector ID if rendered and refresh button."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == connector_id:
                self._update_test_button_for_row(row, connector_id)
                break

    def _on_connection_changed(self, status: str) -> None:
        """Update test button interactivity based on connection state."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                cid = item.data(Qt.ItemDataRole.UserRole)
                if cid:
                    self._update_test_button_for_row(row, cid)

    def _on_connectors_updated(self, connectors: List[ConnectorDTO], ts) -> None:
        self.count_lbl.setText(f"({len(connectors)} registered)")
        self.table.setRowCount(len(connectors))

        for row, conn in enumerate(connectors):
            # Name (storing connector_id on UserRole for safe lookups)
            name_item = QTableWidgetItem(f"{conn.name} ({conn.connector_id[:8]})")
            name_item.setData(Qt.ItemDataRole.UserRole, conn.connector_id)
            self.table.setItem(row, 0, name_item)

            # Type
            self.table.setItem(row, 1, QTableWidgetItem(conn.connector_type))

            # Operational Status
            op_stat = conn.health.operational_status if conn.health else "unknown"
            op_badge = StatusBadge(op_stat, op_stat)
            self.table.setCellWidget(row, 2, op_badge)

            # Target Status
            tgt_stat = conn.health.target_status if conn.health else "unknown"
            tgt_badge = StatusBadge(tgt_stat, tgt_stat)
            self.table.setCellWidget(row, 3, tgt_badge)

            # Errors
            err_cnt = str(conn.health.consecutive_operational_errors) if conn.health else "0"
            self.table.setItem(row, 4, QTableWidgetItem(err_cnt))

            # Last Poll
            poll_str = conn.health.last_poll_at.strftime("%H:%M:%S") if (conn.health and conn.health.last_poll_at) else "Never"
            self.table.setItem(row, 5, QTableWidgetItem(poll_str))

            # Actions: Test Connection (no widget captures in closure!)
            btn_test = QPushButton("Test", self)
            btn_test.setStyleSheet("background-color: #334155; color: #F1F5F9; padding: 2px 8px; font-size: 11px;")
            btn_test.clicked.connect(lambda _, cid=conn.connector_id: self._test_connector(cid))
            self.table.setCellWidget(row, 6, btn_test)

            self._update_test_button_for_row(row, conn.connector_id)

    def _test_connector(self, connector_id: str) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot test connector while offline.")
            return

        if connector_id in self._testing_connector_ids:
            return  # Duplicate test in flight guard

        self._testing_connector_ids.add(connector_id)
        self._sync_test_button_for_connector(connector_id)

        def worker():
            return self.client.test_connector(connector_id)

        def on_success(result):
            self._testing_connector_ids.discard(connector_id)
            self._sync_test_button_for_connector(connector_id)
            status = result.get("status", "unknown")
            latency = result.get("latency_ms", "N/A")
            msg = f"Ping {status.upper()} (Latency: {latency}ms)"
            app_signals.action_succeeded.emit("Connector Diagnostic", msg)

        def on_error(exc: Exception):
            self._testing_connector_ids.discard(connector_id)
            self._sync_test_button_for_connector(connector_id)
            app_signals.action_failed.emit("Connector Test Failed", str(exc))

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _on_project_changed(self, project_id: str) -> None:
        """Handle project selection change by displaying cached data and triggering a fresh fetch."""
        if not project_id:
            self._on_connectors_updated([], None)
            return

        # 1. Immediately hydrate from in-memory cache if available
        if project_id in self.state.cached_connectors:
            cached_conns, ts = self.state.cached_connectors[project_id]
            self._on_connectors_updated(cached_conns, ts)
        else:
            self._on_connectors_updated([], None)

        # 2. Fetch latest connectors for the project asynchronously
        self.refresh()

    def on_view_activated(self) -> None:
        """Invoked when user navigates to Connectors tab."""
        active_id = self.state.active_project_id
        if active_id:
            # Rehydrate from cached connectors or trigger refresh if empty
            if active_id in self.state.cached_connectors:
                cached_conns, ts = self.state.cached_connectors[active_id]
                self._on_connectors_updated(cached_conns, ts)
            else:
                self.refresh()

    def refresh(self) -> None:
        """Asynchronously fetch registered connectors for active project."""
        project_id = self.state.active_project_id
        if not project_id or not self.state.is_online():
            return

        def worker():
            return self.client.list_connectors(project_id=project_id)

        def on_success(connectors: List[ConnectorDTO]):
            if self.state.active_project_id == project_id:
                self.state.set_connectors(project_id, connectors)
            else:
                now = datetime.now(timezone.utc)
                self.state.cached_connectors[project_id] = (connectors, now)

        def on_error(exc: Exception):
            pass

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)
