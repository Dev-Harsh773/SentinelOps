"""Incidents list, filtering, and deep-investigation detail drawer view."""

from typing import List, Optional
try:
    from PyQt6.sip import isdeleted
except (ImportError, ModuleNotFoundError):
    try:
        import sip
        isdeleted = sip.isdeleted
    except (ImportError, ModuleNotFoundError, AttributeError):
        def isdeleted(obj: object) -> bool:
            return False

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.api.client import SentinelOpsClient
from desktop.api.models import (
    EvidenceDTO,
    IncidentDTO,
    IncidentReportDTO,
    InvestigationDTO,
    RemediationBranchDTO,
    RemediationDTO,
    RemediationReviewDTO,
    SafeActionDTO,
)
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals

from desktop.ui.components.status_badge import StatusBadge
from desktop.workers.task_runner import TaskRunner


class IncidentsView(QWidget):
    """Interactive table of incidents with side-by-side deep inspection drawer."""

    def __init__(self, client: SentinelOpsClient, task_runner: TaskRunner, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.task_runner = task_runner
        self.state = AppState()

        self._all_incidents: List[IncidentDTO] = []
        self._selected_incident: Optional[IncidentDTO] = None
        self._loading_incident_id: Optional[str] = None
        self._transitioning_incident_ids: set[str] = set()
        self._actions_in_flight: set[str] = set()
        self._is_refreshing: bool = False
        self._refresh_generation: int = 0

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # Title & Filter Bar
        header_layout = QHBoxLayout()
        title_lbl = QLabel("Incidents", self)
        title_lbl.setStyleSheet("font-size: 20px; font-weight: 700; color: #F8FAFC;")
        header_layout.addWidget(title_lbl)

        header_layout.addStretch()

        # Search filter
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search title, service, environment...")
        self.search_input.setMinimumWidth(220)
        self.search_input.textChanged.connect(self._apply_filters)
        header_layout.addWidget(self.search_input)

        # Severity filter
        self.sev_filter = QComboBox(self)
        self.sev_filter.addItems(["All Severities", "Critical", "High", "Medium", "Low"])
        self.sev_filter.currentIndexChanged.connect(self._apply_filters)
        header_layout.addWidget(self.sev_filter)

        # Status filter
        self.status_filter = QComboBox(self)
        self.status_filter.addItems(["All Statuses", "Open", "Investigating", "Resolved", "Closed"])
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        header_layout.addWidget(self.status_filter)

        main_layout.addLayout(header_layout)

        # Splitter: Table on left, Detail Drawer on right
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)

        # Left: Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Severity", "Status", "Title", "Service", "Env", "Created (UTC)"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 85)
        self.table.setColumnWidth(1, 115)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 75)
        self.table.setColumnWidth(5, 130)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.splitter.addWidget(self.table)

        # Right: Detail Drawer
        self.detail_panel = self._create_detail_panel()
        self.splitter.addWidget(self.detail_panel)
        self.splitter.setSizes([700, 480])

        main_layout.addWidget(self.splitter)

        # Signals
        app_signals.incidents_updated.connect(self._on_incidents_updated)
        app_signals.connection_changed.connect(self._on_connection_changed)
        app_signals.active_project_changed.connect(self._on_project_changed)

    def _on_project_changed(self, project_id: str) -> None:
        """Reset selection, invalidate in-flight refreshes, and scope table to new project."""
        self._refresh_generation += 1
        self._is_refreshing = False
        self._actions_in_flight.clear()
        self._clear_incident_detail()
        if project_id and project_id in self.state.cached_incidents:
            cached_list, _ = self.state.cached_incidents[project_id]
            self._all_incidents = [i for i in cached_list if i.project_id == project_id]
        else:
            self._all_incidents = []
        self._apply_filters()

    def _create_detail_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setProperty("class", "Card")
        p_layout = QVBoxLayout(panel)
        p_layout.setContentsMargins(14, 14, 14, 14)
        p_layout.setSpacing(10)

        # Detail Header
        self.d_title = QLabel("Select an incident to view details", panel)
        self.d_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #F8FAFC;")
        self.d_title.setWordWrap(True)
        p_layout.addWidget(self.d_title)

        meta_row = QHBoxLayout()
        self.d_sev_badge = StatusBadge("info", "info", panel)
        self.d_status_badge = StatusBadge("open", "open", panel)
        self.d_meta_lbl = QLabel("", panel)
        self.d_meta_lbl.setStyleSheet("color: #94A3B8; font-size: 12px;")

        meta_row.addWidget(self.d_sev_badge)
        meta_row.addWidget(self.d_status_badge)
        meta_row.addWidget(self.d_meta_lbl)
        meta_row.addStretch()
        p_layout.addLayout(meta_row)

        # Lifecycle Action Buttons (Server-Confirmed!)
        self.actions_row = QHBoxLayout()
        self.btn_investigate = QPushButton("Investigate", panel)
        self.btn_investigate.clicked.connect(lambda: self._trigger_status_transition("investigating"))
        self.btn_resolve = QPushButton("Resolve", panel)
        self.btn_resolve.clicked.connect(lambda: self._trigger_status_transition("resolved"))
        self.btn_close = QPushButton("Close", panel)
        self.btn_close.clicked.connect(lambda: self._trigger_status_transition("closed"))

        self.actions_row.addWidget(self.btn_investigate)
        self.actions_row.addWidget(self.btn_resolve)
        self.actions_row.addWidget(self.btn_close)
        self.actions_row.addStretch()
        p_layout.addLayout(self.actions_row)

        # Tabs for Deep Investigation, Remediation, and Evidence
        self.tabs = QTabWidget(panel)

        # Tab 1: Summary
        self.summary_text = QTextEdit(self.tabs)
        self.summary_text.setReadOnly(True)
        self.tabs.addTab(self.summary_text, "Summary")

        # Tab 2: Unified Report
        self.report_widget = QWidget(self.tabs)
        r_layout = QVBoxLayout(self.report_widget)
        r_layout.setContentsMargins(6, 6, 6, 6)
        r_btn_row = QHBoxLayout()
        self.btn_copy_markdown = QPushButton("Copy Markdown", self.report_widget)
        self.btn_copy_markdown.setToolTip("Copy complete markdown report to clipboard")
        self.btn_copy_markdown.clicked.connect(self._copy_report_markdown)
        r_btn_row.addStretch()
        r_btn_row.addWidget(self.btn_copy_markdown)
        r_layout.addLayout(r_btn_row)
        self.report_text = QTextEdit(self.report_widget)
        self.report_text.setReadOnly(True)
        r_layout.addWidget(self.report_text)
        self.tabs.addTab(self.report_widget, "Report")

        # Tab 3: Timeline
        self.timeline_text = QTextEdit(self.tabs)
        self.timeline_text.setReadOnly(True)
        self.tabs.addTab(self.timeline_text, "Timeline")

        # Tab 4: Evidence
        self.evidence_text = QTextEdit(self.tabs)
        self.evidence_text.setReadOnly(True)
        self.tabs.addTab(self.evidence_text, "Evidence")

        # Tab 5: Investigation (Read-Only)
        self.investigation_text = QTextEdit(self.tabs)
        self.investigation_text.setReadOnly(True)
        self.tabs.addTab(self.investigation_text, "AI Investigation")

        # Tab 6: Remediation (Read-Only)
        self.remediation_text = QTextEdit(self.tabs)
        self.remediation_text.setReadOnly(True)
        self.tabs.addTab(self.remediation_text, "Remediation")

        # Tab 7: Safe Actions
        self.actions_scroll = QScrollArea(self.tabs)
        self.actions_scroll.setWidgetResizable(True)
        self.actions_widget = QWidget()
        self.actions_layout = QVBoxLayout(self.actions_widget)
        self.actions_layout.setContentsMargins(10, 10, 10, 10)
        self.actions_layout.setSpacing(10)
        self.actions_scroll.setWidget(self.actions_widget)
        self.tabs.addTab(self.actions_scroll, "Safe Actions")

        # Tab 8: Operational Memory
        self.memory_text = QTextEdit(self.tabs)
        self.memory_text.setReadOnly(True)
        self.tabs.addTab(self.memory_text, "Operational Memory")

        p_layout.addWidget(self.tabs)
        self._clear_incident_detail()
        return panel


    def _render_neutral_empty_safe_actions(self, message: str = "No incident selected.") -> None:
        """Render a clean, neutral empty-state message in the Safe Actions tab."""
        if not self._is_safe_to_update_ui():
            return
        try:
            while self.actions_layout.count():
                item = self.actions_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            lbl = QLabel(message, self.actions_widget)
            lbl.setStyleSheet("color: #94A3B8; font-style: italic;")
            self.actions_layout.addWidget(lbl)
            self.actions_layout.addStretch()
        except (RuntimeError, ReferenceError):
            pass

    def _clear_incident_detail(self) -> None:
        """Clear stale detail pane and restore neutral empty state across all tabs."""
        self._selected_incident = None
        self._loading_incident_id = None
        self._set_detail_enabled(False)

        # Clear table selection
        self.table.blockSignals(True)
        try:
            self.table.clearSelection()
        finally:
            self.table.blockSignals(False)

        # Reset header and metadata
        self.d_title.setText("Select an incident to view details")
        self.d_sev_badge.hide()
        self.d_status_badge.hide()
        self.d_meta_lbl.setText("No incident selected")

        # Neutral empty text on inspection tabs
        self.summary_text.setHtml("<p style='color: #94A3B8; font-style: italic;'>No incident selected.</p>")
        self.report_text.setHtml("<p style='color: #94A3B8; font-style: italic;'>No incident selected.</p>")
        self.timeline_text.setPlainText("No incident selected.")
        self.evidence_text.setPlainText("No incident selected.")
        self.investigation_text.setPlainText("No incident selected.")
        self.remediation_text.setPlainText("No incident selected.")
        self.memory_text.setPlainText("No incident selected.")

        # Safe Actions empty state
        self._render_neutral_empty_safe_actions("No incident selected.")


    def _set_detail_enabled(self, enabled: bool) -> None:
        self.tabs.setEnabled(enabled)
        if not enabled:
            self.btn_investigate.hide()
            self.btn_resolve.hide()
            self.btn_close.hide()
        else:
            self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        is_online = self.state.is_online()
        if not self._selected_incident:
            self.btn_investigate.hide()
            self.btn_resolve.hide()
            self.btn_close.hide()
            return

        status = (self._selected_incident.status or "").lower()
        tooltip_offline = "Unavailable while offline"

        if status == "open":
            self.btn_investigate.show()
            self.btn_investigate.setEnabled(is_online)
            self.btn_investigate.setToolTip("" if is_online else tooltip_offline)

            self.btn_resolve.show()
            self.btn_resolve.setEnabled(is_online)
            self.btn_resolve.setToolTip("" if is_online else tooltip_offline)

            self.btn_close.hide()
        elif status == "investigating":
            self.btn_investigate.hide()

            self.btn_resolve.show()
            self.btn_resolve.setEnabled(is_online)
            self.btn_resolve.setToolTip("" if is_online else tooltip_offline)

            self.btn_close.hide()
        elif status == "resolved":
            self.btn_investigate.hide()
            self.btn_resolve.hide()

            self.btn_close.show()
            self.btn_close.setEnabled(is_online)
            self.btn_close.setToolTip("" if is_online else tooltip_offline)
        else:  # closed or other terminal state
            self.btn_investigate.hide()
            self.btn_resolve.hide()
            self.btn_close.hide()

    def _on_connection_changed(self, status: str) -> None:
        if self._selected_incident:
            self._update_action_buttons()

    def _on_incidents_updated(self, incidents: List[IncidentDTO], ts) -> None:
        if not self._is_safe_to_update_ui():
            return

        active_project = self.state.active_project_id
        if active_project:
            # Canonical project-scoping invariant: strictly drop any cross-project incidents
            scoped_incidents = [i for i in incidents if i.project_id == active_project]
        else:
            scoped_incidents = list(incidents)

        prev_selected_id = self._selected_incident.id if self._selected_incident else None
        self._all_incidents = scoped_incidents
        self._apply_filters()

        if prev_selected_id:
            match = next((i for i in self._all_incidents if i.id == prev_selected_id), None)
            if match:
                self._selected_incident = match
                self._restore_table_selection(prev_selected_id)
                self._render_incident_detail(match)
            else:
                self._clear_incident_detail()
        else:
            if not self._all_incidents:
                self._clear_incident_detail()

    def _restore_table_selection(self, incident_id: str) -> None:
        """Restore row selection in table without emitting redundant selection changed signals."""
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 2)
                if item and item.data(Qt.ItemDataRole.UserRole) == incident_id:
                    self.table.selectRow(row)
                    break
        finally:
            self.table.blockSignals(False)

    def _apply_filters(self) -> None:
        active_project = self.state.active_project_id
        query = self.search_input.text().strip().lower()
        sev_choice = self.sev_filter.currentText().lower()
        status_choice = self.status_filter.currentText().lower()

        filtered = []
        for inc in self._all_incidents:
            # Authoritative project guard: never allow cross-project incident into filtered list
            if active_project and inc.project_id != active_project:
                continue
            if sev_choice != "all severities" and inc.severity != sev_choice:
                continue
            if status_choice != "all statuses" and inc.status != status_choice:
                continue
            if query:
                match = (
                    query in inc.title.lower()
                    or query in inc.service.lower()
                    or query in inc.environment.lower()
                    or query in inc.summary.lower()
                )
                if not match:
                    continue
            filtered.append(inc)

        self._populate_table(filtered)

    def _populate_table(self, incidents: List[IncidentDTO]) -> None:
        active_project = self.state.active_project_id
        if active_project:
            # Absolute invariant: no incident outside active project is ever rendered in the table
            incidents = [i for i in incidents if i.project_id == active_project]
        self.table.setRowCount(len(incidents))
        for row, inc in enumerate(incidents):
            # Severity
            sev_badge = StatusBadge(inc.severity, inc.severity)
            self.table.setCellWidget(row, 0, sev_badge)

            # Status
            stat_badge = StatusBadge(inc.status, inc.status)
            self.table.setCellWidget(row, 1, stat_badge)

            # Title
            t_item = QTableWidgetItem(inc.title)
            t_item.setData(Qt.ItemDataRole.UserRole, inc.id)
            self.table.setItem(row, 2, t_item)

            # Service
            self.table.setItem(row, 3, QTableWidgetItem(inc.service))

            # Environment
            self.table.setItem(row, 4, QTableWidgetItem(inc.environment))

            # Created
            c_str = inc.created_at.strftime("%Y-%m-%d %H:%M") if inc.created_at else ""
            self.table.setItem(row, 5, QTableWidgetItem(c_str))

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Handle cell click to ensure re-selection fetches fresh details & safe actions even if already selected."""
        item = self.table.item(row, 2)
        if not item:
            return
        inc_id = item.data(Qt.ItemDataRole.UserRole)
        match = next((i for i in self._all_incidents if i.id == inc_id), None)
        if match:
            self._selected_incident = match
            self._render_incident_detail(match)

    def _on_row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return

        row = rows[0].row()
        item = self.table.item(row, 2)
        if not item:
            return
        inc_id = item.data(Qt.ItemDataRole.UserRole)
        match = next((i for i in self._all_incidents if i.id == inc_id), None)
        if not match:
            return

        self._selected_incident = match
        self._render_incident_detail(match)

    def on_view_activated(self) -> None:
        """Invoked when user navigates to the Incidents tab."""
        if not self._is_safe_to_update_ui():
            return
        if self._selected_incident:
            self._render_incident_detail(self._selected_incident)

    def refresh(self) -> None:
        """Asynchronously refresh the incident list and active incident's safe actions."""
        if not self._is_safe_to_update_ui():
            return
        if self._is_refreshing:
            return
        self._is_refreshing = True
        self._refresh_generation += 1
        current_gen = self._refresh_generation
        target_project_id = self.state.active_project_id

        def worker():
            return self.client.list_incidents()

        def on_success(incidents: List[IncidentDTO]):
            self._is_refreshing = False
            if not self._is_safe_to_update_ui():
                return
            # Stale request protection: discard if project changed or newer refresh started
            if current_gen != self._refresh_generation or (target_project_id and self.state.active_project_id != target_project_id):
                return

            # Canonical pipeline: set_incidents_from_all partitions by project and emits incidents_updated
            self.state.set_incidents_from_all(incidents)

            # If an incident is selected and belongs to target project, authoritatively refresh safe actions
            if self._selected_incident and (not target_project_id or self._selected_incident.project_id == target_project_id):
                self._refresh_safe_actions(self._selected_incident.id)

        def on_error(exc: Exception):
            self._is_refreshing = False
            if (
                self._is_safe_to_update_ui()
                and current_gen == self._refresh_generation
                and (not target_project_id or self.state.active_project_id == target_project_id)
                and self._selected_incident
            ):
                self._refresh_safe_actions(self._selected_incident.id)

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _render_safe_actions_loading(self) -> None:
        """Display loading placeholder in Safe Actions tab while server query is in flight."""
        if not self._is_safe_to_update_ui():
            return
        try:
            while self.actions_layout.count():
                item = self.actions_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            lbl = QLabel("Loading safe actions...", self.actions_widget)
            lbl.setStyleSheet("color: #94A3B8; font-style: italic;")
            self.actions_layout.addWidget(lbl)
            self.actions_layout.addStretch()
        except (RuntimeError, ReferenceError):
            pass

    def _render_incident_detail(self, inc: IncidentDTO) -> None:
        self._set_detail_enabled(True)
        self.d_title.setText(inc.title)
        self.d_sev_badge.show()
        self.d_status_badge.show()
        self.d_sev_badge.set_value(inc.severity, inc.severity)
        self.d_status_badge.set_value(inc.status, inc.status)
        self.d_meta_lbl.setText(f"{inc.service} | {inc.environment} | ID: {inc.id[:8]}")

        # Summary Tab
        self.summary_text.setHtml(
            f"<h3>Summary</h3><p>{inc.summary}</p>"
            f"<p><b>Service:</b> {inc.service}<br>"
            f"<b>Environment:</b> {inc.environment}<br>"
            f"<b>Created:</b> {inc.created_at}<br>"
            f"<b>Updated:</b> {inc.updated_at}</p>"
        )

        # Asynchronously fetch evidence, investigation, remediation, actions, and unified report
        self._loading_incident_id = inc.id
        self.evidence_text.setPlainText("Loading evidence...")
        self.investigation_text.setPlainText("Loading investigation...")
        self.remediation_text.setPlainText("Loading remediation...")
        self.report_text.setHtml("<p style='color: #94A3B8; font-style: italic;'>Loading unified report...</p>")
        self.timeline_text.setPlainText("Loading timeline...")
        self.memory_text.setPlainText("Loading operational memory...")
        self._render_safe_actions_loading()

        active_proj = self.state.active_project_id or inc.project_id

        def fetch_artifacts():
            ev = self.client.list_incident_evidence(inc.id)
            inv = self.client.get_incident_investigation(inc.id)
            rem = self.client.get_incident_remediation(inc.id)
            rev = self.client.list_remediation_reviews(inc.id) if rem else []
            branch = self.client.get_remediation_branch(inc.id) if rem else None
            actions = self.client.list_actions(incident_id=inc.id)
            report = None
            try:
                report = self.client.get_incident_report(inc.id, project_id=active_proj)
            except Exception:
                pass
            return ev, inv, rem, rev, branch, actions, report

        def on_success(artifacts):
            if (
                not self._is_safe_to_update_ui()
                or self._loading_incident_id != inc.id
                or not self._selected_incident
                or self._selected_incident.id != inc.id
                or (self.state.active_project_id and self._selected_incident.project_id != self.state.active_project_id)
            ):
                return  # Stale response discarded
            ev, inv, rem, rev, branch, actions, report = artifacts
            self._render_evidence(ev)
            self._render_investigation(inv)
            self._render_remediation(rem, rev, branch)
            self._render_safe_actions(actions)
            if report and isinstance(report, IncidentReportDTO):
                self._render_report(report)
            else:
                self.report_text.setHtml("<p style='color: #94A3B8; font-style: italic;'>Report unavailable.</p>")
                self.timeline_text.setPlainText("Timeline unavailable.")
                self.memory_text.setPlainText("Operational memory unavailable.")

        def on_error(exc):
            if (
                not self._is_safe_to_update_ui()
                or self._loading_incident_id != inc.id
                or not self._selected_incident
                or self._selected_incident.id != inc.id
                or (self.state.active_project_id and self._selected_incident.project_id != self.state.active_project_id)
            ):
                return  # Stale response discarded
            self.evidence_text.setPlainText(f"Failed to load evidence: {exc}")
            self.investigation_text.setPlainText(f"Failed to load investigation: {exc}")
            self.remediation_text.setPlainText(f"Failed to load remediation: {exc}")
            self.report_text.setHtml(f"<p style='color: #EF4444;'>Failed to load report: {exc}</p>")
            self.timeline_text.setPlainText(f"Failed to load timeline: {exc}")
            self.memory_text.setPlainText(f"Failed to load operational memory: {exc}")
            self._render_safe_actions([])


        self.task_runner.run(fetch_artifacts, on_success=on_success, on_error=on_error)

    def _render_evidence(self, items: List[EvidenceDTO]) -> None:
        if not items:
            self.evidence_text.setPlainText("No runtime evidence attached to this incident.")
            return
        lines = []
        for i, e in enumerate(items, 1):
            lines.append(f"[{i}] {e.log_level} | Signal: {e.signal_type} | Source: {e.source_file}")
            if e.request_id:
                lines.append(f"    Request ID: {e.request_id}")
            lines.append(f"    Message: {e.message}\n")
        self.evidence_text.setPlainText("\n".join(lines))

    def _render_investigation(self, inv: Optional[InvestigationDTO]) -> None:
        if not inv:
            self.investigation_text.setPlainText("No AI investigation has been completed for this incident.")
            return
        html = [f"<h3>Investigation (Status: {inv.status.upper()})</h3>"]
        if inv.rca:
            rca = inv.rca
            html.append(f"<p><b>Root Cause Hypothesis:</b><br>{rca.root_cause_hypothesis}</p>")
            html.append(f"<p><b>Summary:</b> {rca.summary}</p>")
            html.append(f"<p><b>Triggering Condition:</b> {rca.triggering_condition}</p>")
            html.append(f"<p><b>Failure Location:</b> {rca.failure_location}</p>")
            html.append(f"<p><b>Confidence:</b> {int(rca.confidence * 100)}%</p>")
            if rca.supporting_evidence:
                html.append("<b>Supporting Evidence:</b><ul>")
                for sup in rca.supporting_evidence:
                    html.append(f"<li>{sup.type}: {sup.id} ({sup.description or ''})</li>")
                html.append("</ul>")
        self.investigation_text.setHtml("".join(html))

    def _render_remediation(
        self,
        rem: Optional[RemediationDTO],
        reviews: List[RemediationReviewDTO],
        branch: Optional[RemediationBranchDTO],
    ) -> None:
        if not rem:
            self.remediation_text.setPlainText("No remediation proposal exists for this incident.")
            return
        html = [f"<h3>Proposed Remediation (Status: {rem.status.upper()})</h3>"]
        html.append(f"<p><b>Summary:</b> {rem.summary}</p>")
        html.append(f"<p><b>Rationale:</b> {rem.rationale}</p>")
        if rem.proposed_changes:
            html.append("<b>Proposed Changes:</b><ul>")
            for ch in rem.proposed_changes:
                html.append(f"<li><code>{ch.file_path}</code> ({ch.change_type}): {ch.description}</li>")
            html.append("</ul>")
        if rem.risks:
            html.append(f"<p style='color: #FBBF24;'><b>Identified Risks:</b><br>{'<br>'.join(rem.risks)}</p>")
        if branch:
            html.append(f"<p style='color: #60A5FA;'><b>Git Branch:</b> <code>{branch.branch_name}</code> (Base: {branch.base_branch})</p>")
        if reviews:
            html.append("<b>Review Audit Trail:</b><ul>")
            for rev in reviews:
                html.append(f"<li><b>{rev.decision.upper()}</b> by {rev.reviewer} ({rev.created_at}): {rev.comment or ''}</li>")
            html.append("</ul>")
        self.remediation_text.setHtml("".join(html))

    def _trigger_status_transition(self, new_status: str) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot transition incident status while offline.")
            return
        if not self._selected_incident:
            return
        inc_id = self._selected_incident.id
        if inc_id in self._transitioning_incident_ids:
            return  # Duplicate transition in flight guard

        self._transitioning_incident_ids.add(inc_id)
        self._set_detail_enabled(False)

        def worker():
            return self.client.update_incident_status(inc_id, new_status)

        def on_success(updated: IncidentDTO):
            self._transitioning_incident_ids.discard(inc_id)
            self._set_detail_enabled(True)

            # Update cache if matching active project
            if self.state.active_project_id == updated.project_id:
                for i, item in enumerate(self._all_incidents):
                    if item.id == updated.id:
                        self._all_incidents[i] = updated
                        break
                self._apply_filters()

            # Only re-render detail drawer if user is still actively viewing this incident
            if self._selected_incident and self._selected_incident.id == updated.id:
                self._selected_incident = updated
                self._render_incident_detail(updated)

            app_signals.action_succeeded.emit("Status Updated", f"Incident transitioned to {new_status.upper()}")

        def on_error(exc: Exception):
            self._transitioning_incident_ids.discard(inc_id)
            self._set_detail_enabled(True)
            if self._selected_incident and self._selected_incident.id == inc_id:
                self._update_action_buttons(self._selected_incident.status)
            app_signals.action_failed.emit("Transition Rejected", str(exc))

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _is_safe_to_update_ui(self) -> bool:
        """Verify that this view and its child widgets are still alive."""
        try:
            if isdeleted(self):
                return False
            if hasattr(self, "actions_widget") and isdeleted(self.actions_widget):
                return False
            if hasattr(self, "actions_layout") and isdeleted(self.actions_layout):
                return False
            return True
        except (RuntimeError, ReferenceError):
            return False

    def _refresh_safe_actions(self, incident_id: str) -> None:
        """Fetch and update safe actions for the incident without reloading entire drawer."""
        if not self._is_safe_to_update_ui():
            return

        def fetch():
            return self.client.list_actions(incident_id=incident_id)

        def on_success(actions):
            if (
                not self._is_safe_to_update_ui()
                or not self._selected_incident
                or self._selected_incident.id != incident_id
                or (self.state.active_project_id and self._selected_incident.project_id != self.state.active_project_id)
            ):
                return
            self._render_safe_actions(actions)

        def on_error(exc):
            pass

        self.task_runner.run(fetch, on_success=on_success, on_error=on_error)

    def _render_safe_actions(self, actions: List[SafeActionDTO]) -> None:
        if not self._is_safe_to_update_ui():
            return

        try:
            # Clear previous cards
            while self.actions_layout.count():
                item = self.actions_layout.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()

            if not actions:
                lbl = QLabel("No safe actions proposed for this incident.", self.actions_widget)
                lbl.setStyleSheet("color: #94A3B8; font-style: italic;")
                self.actions_layout.addWidget(lbl)
                self.actions_layout.addStretch()
                return

            for action in actions:
                card = QFrame(self.actions_widget)
                card.setProperty("class", "Card")
                card.setStyleSheet("background: #1E293B; border-radius: 6px; padding: 10px; margin-bottom: 6px;")
                c_layout = QVBoxLayout(card)
                c_layout.setSpacing(6)

                top_row = QHBoxLayout()
                type_lbl = QLabel(f"<b>{action.action_type.upper()}</b> on {action.target_type}:{action.target_id[:8]}", card)
                type_lbl.setStyleSheet("color: #F8FAFC; font-size: 13px;")
                top_row.addWidget(type_lbl)
                top_row.addStretch()

                policy_badge = StatusBadge(action.policy_status, action.policy_status, card)
                approval_badge = StatusBadge(action.approval_status, action.approval_status, card)
                exec_badge = StatusBadge(action.execution_status, action.execution_status, card)

                top_row.addWidget(policy_badge)
                top_row.addWidget(approval_badge)
                top_row.addWidget(exec_badge)
                c_layout.addLayout(top_row)

                # Fingerprint and actor info
                info_lbl = QLabel(
                    f"<span style='color:#94A3B8;'>Fingerprint:</span> {action.fingerprint[:12]}... | "
                    f"<span style='color:#94A3B8;'>Requested by:</span> {action.requested_by_claim}",
                    card,
                )
                info_lbl.setStyleSheet("font-size: 11px;")
                c_layout.addWidget(info_lbl)

                if action.failure_reason:
                    err_lbl = QLabel(f"<span style='color:#EF4444;'>Reason/Error:</span> {action.failure_reason}", card)
                    err_lbl.setWordWrap(True)
                    c_layout.addWidget(err_lbl)

                if action.execution_result:
                    res_lbl = QLabel(f"<span style='color:#10B981;'>Result:</span> {action.execution_result}", card)
                    res_lbl.setWordWrap(True)
                    c_layout.addWidget(res_lbl)

                # Controls
                btn_row = QHBoxLayout()
                is_online = self.state.is_online()
                is_in_flight = action.action_id in self._actions_in_flight

                if action.approval_status == "pending" and action.policy_status == "allowed":
                    approve_btn = QPushButton("Approve", card)
                    approve_btn.setEnabled(is_online and not is_in_flight)
                    approve_btn.clicked.connect(lambda _, a=action: self._approve_action(a.action_id))
                    reject_btn = QPushButton("Reject", card)
                    reject_btn.setEnabled(is_online and not is_in_flight)
                    reject_btn.clicked.connect(lambda _, a=action: self._reject_action(a.action_id))
                    btn_row.addWidget(approve_btn)
                    btn_row.addWidget(reject_btn)

                elif action.approval_status == "approved" and action.execution_status == "not_started":
                    exec_btn = QPushButton("Execute Action", card)
                    exec_btn.setStyleSheet("background: #0284C7; color: white; font-weight: bold;")
                    if is_in_flight:
                        exec_btn.setText("Executing...")
                        exec_btn.setEnabled(False)
                    else:
                        exec_btn.setText("Execute Action")
                        exec_btn.setEnabled(is_online)
                    exec_btn.clicked.connect(lambda _, a=action: self._execute_action(a.action_id))
                    btn_row.addWidget(exec_btn)

                elif action.execution_status == "executing" or is_in_flight:
                    exec_lbl = QLabel("<span style='color:#38BDF8;'><b>Executing...</b></span>", card)
                    btn_row.addWidget(exec_lbl)

                btn_row.addStretch()
                if btn_row.count() > 1:
                    c_layout.addLayout(btn_row)

                self.actions_layout.addWidget(card)

            self.actions_layout.addStretch()
        except (RuntimeError, ReferenceError):
            pass

    def _approve_action(self, action_id: str) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot approve safe action while offline.")
            return

        if action_id in self._actions_in_flight:
            return

        if not self._selected_incident:
            return

        inc_id = self._selected_incident.id

        operator, ok = QInputDialog.getText(self, "Approve Safe Action", "Enter operator attribution claim (e.g. operator:admin):")
        if not ok or not operator.strip():
            return
        comment, _ = QInputDialog.getText(self, "Approval Comment", "Enter optional comment:")

        self._actions_in_flight.add(action_id)
        self._refresh_safe_actions(inc_id)

        def worker():
            return self.client.approve_action(action_id, operator.strip(), comment.strip() if comment else None)

        def on_success(updated):
            self._actions_in_flight.discard(action_id)
            app_signals.action_succeeded.emit("Action Approved", f"Safe action {action_id[:8]} approved.")
            if self._is_safe_to_update_ui() and self._selected_incident and self._selected_incident.id == inc_id:
                self._refresh_safe_actions(inc_id)

        def on_error(exc):
            self._actions_in_flight.discard(action_id)
            app_signals.action_failed.emit("Approval Failed", str(exc))
            if self._is_safe_to_update_ui() and self._selected_incident and self._selected_incident.id == inc_id:
                self._refresh_safe_actions(inc_id)

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _reject_action(self, action_id: str) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot reject safe action while offline.")
            return

        if action_id in self._actions_in_flight:
            return

        if not self._selected_incident:
            return

        inc_id = self._selected_incident.id

        operator, ok = QInputDialog.getText(self, "Reject Safe Action", "Enter operator attribution claim (e.g. operator:admin):")
        if not ok or not operator.strip():
            return
        reason, ok2 = QInputDialog.getText(self, "Rejection Reason", "Enter rejection reason:")
        if not ok2 or not reason.strip():
            return

        self._actions_in_flight.add(action_id)
        self._refresh_safe_actions(inc_id)

        def worker():
            return self.client.reject_action(action_id, operator.strip(), reason.strip())

        def on_success(updated):
            self._actions_in_flight.discard(action_id)
            app_signals.action_succeeded.emit("Action Rejected", f"Safe action {action_id[:8]} rejected.")
            if self._is_safe_to_update_ui() and self._selected_incident and self._selected_incident.id == inc_id:
                self._refresh_safe_actions(inc_id)

        def on_error(exc):
            self._actions_in_flight.discard(action_id)
            app_signals.action_failed.emit("Rejection Failed", str(exc))
            if self._is_safe_to_update_ui() and self._selected_incident and self._selected_incident.id == inc_id:
                self._refresh_safe_actions(inc_id)

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _execute_action(self, action_id: str) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot execute safe action while offline.")
            return

        if action_id in self._actions_in_flight:
            return

        if not self._selected_incident:
            return

        inc_id = self._selected_incident.id

        self._actions_in_flight.add(action_id)
        self._refresh_safe_actions(inc_id)

        def worker():
            return self.client.execute_action(action_id)

        def on_success(updated):
            self._actions_in_flight.discard(action_id)
            app_signals.action_succeeded.emit(
                "Execution Completed",
                f"Action {action_id[:8]} status: {updated.execution_status.upper()}",
            )
            if self._is_safe_to_update_ui() and self._selected_incident and self._selected_incident.id == inc_id:
                self._refresh_safe_actions(inc_id)

        def on_error(exc):
            self._actions_in_flight.discard(action_id)
            app_signals.action_failed.emit("Execution Error", str(exc))
            if self._is_safe_to_update_ui() and self._selected_incident and self._selected_incident.id == inc_id:
                self._refresh_safe_actions(inc_id)

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _copy_report_markdown(self) -> None:
        """Copies the current report in markdown format to the system clipboard."""
        if not hasattr(self, "_current_report_markdown") or not self._current_report_markdown:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self._current_report_markdown)
            app_signals.action_succeeded.emit("Report Copied", "Markdown report copied to clipboard.")

    def _render_report(self, report: IncidentReportDTO) -> None:
        """Renders rich HTML in the Report tab and formats raw markdown for clipboard copy."""
        if not isinstance(report, IncidentReportDTO):
            return
        inc = report.incident
        det = report.detection_and_evidence
        inv = report.investigation
        rem = report.remediation

        md_lines = []
        md_lines.append(f"# Incident Report: {inc.get('title', 'Untitled')}")
        md_lines.append(f"**Incident ID:** {inc.get('incident_id', '')} | **Project:** {inc.get('project_id', '')}")
        md_lines.append(f"**Severity:** {inc.get('severity', '').upper()} | **Status:** {inc.get('status', '').upper()}")
        md_lines.append(f"**Service:** {inc.get('service', '')} | **Environment:** {inc.get('environment', '')}")
        md_lines.append(f"**Created:** {inc.get('created_at', '')} | **Duration:** {inc.get('duration_seconds') or 'In progress'}")
        md_lines.append("\n## Summary")
        md_lines.append(inc.get("summary", "No summary provided."))

        md_lines.append(f"\n## Detection & Evidence")
        md_lines.append(f"- **Total Evidence Captured:** {det.get('total_evidence_count', 0)}")
        if det.get("first_evidence_at"):
            md_lines.append(f"- **First Evidence:** {det.get('first_evidence_at')}")
        if det.get("last_evidence_at"):
            md_lines.append(f"- **Last Evidence:** {det.get('last_evidence_at')}")

        if inv:
            md_lines.append("\n## Root Cause Analysis (AI Investigation)")
            md_lines.append(f"- **Hypothesis:** {inv.get('root_cause_hypothesis', 'None')}")
            md_lines.append(f"- **Failure Location:** {inv.get('failure_location', 'None')}")
            md_lines.append(f"- **Triggering Condition:** {inv.get('triggering_condition', 'None')}")
            md_lines.append(f"- **Confidence:** {inv.get('confidence', 0.0)}")

        if rem:
            md_lines.append("\n## Remediation Recommendation")
            md_lines.append(f"- **Summary:** {rem.get('summary', 'None')}")
            md_lines.append(f"- **Rationale:** {rem.get('rationale', 'None')}")
            if rem.get("branch_name"):
                md_lines.append(f"- **Branch:** `{rem.get('branch_name')}`")

        if report.safe_actions:
            md_lines.append(f"\n## Safe Actions ({len(report.safe_actions)})")
            for sa in report.safe_actions:
                md_lines.append(f"- **{sa.get('action_type', '').upper()}** on `{sa.get('target_type')}:{sa.get('target_id')}` | Approval: {sa.get('approval_status')} | Execution: {sa.get('execution_status')}")

        if report.similar_incidents:
            md_lines.append(f"\n## Similar Historical Incidents ({len(report.similar_incidents)})")
            for sim in report.similar_incidents:
                md_lines.append(f"- **{sim.title}** (Score: {sim.similarity_score:.1f}) | Signals: {', '.join(sim.matched_signals)}")
                md_lines.append(f"  *Cause:* {sim.root_cause_hypothesis}")

        self._current_report_markdown = "\n".join(md_lines)

        # Build clean HTML for Report widget
        html = f"""
        <div style="font-family: sans-serif; color: #F8FAFC; line-height: 1.5;">
            <h2 style="color: #60A5FA; margin-bottom: 4px;">{inc.get('title')}</h2>
            <p style="color: #94A3B8; font-size: 12px; margin-top: 0;">
                ID: {inc.get('incident_id')} | Project: {inc.get('project_id')} | Service: {inc.get('service')} | Env: {inc.get('environment')}
            </p>
            <p><b>Severity:</b> <span style="color: #F59E0B;">{str(inc.get('severity')).upper()}</span> |
               <b>Status:</b> <span style="color: #10B981;">{str(inc.get('status')).upper()}</span> |
               <b>Duration:</b> {f"{inc.get('duration_seconds'):.1f}s" if inc.get('duration_seconds') is not None else "Active"}
            </p>
            <div style="background: #1E293B; padding: 10px; border-radius: 6px; margin-bottom: 12px;">
                <h4 style="margin: 0 0 6px 0; color: #E2E8F0;">Summary</h4>
                <p style="margin: 0; color: #CBD5E1;">{inc.get('summary')}</p>
            </div>
        """

        if inv:
            html += f"""
            <div style="background: #1E293B; padding: 10px; border-radius: 6px; margin-bottom: 12px;">
                <h4 style="margin: 0 0 6px 0; color: #A78BFA;">Root Cause Analysis</h4>
                <p style="margin: 2px 0;"><b>Hypothesis:</b> {inv.get('root_cause_hypothesis') or 'None'}</p>
                <p style="margin: 2px 0;"><b>Failure Location:</b> <code>{inv.get('failure_location') or 'None'}</code></p>
                <p style="margin: 2px 0;"><b>Triggering Condition:</b> {inv.get('triggering_condition') or 'None'}</p>
                <p style="margin: 2px 0;"><b>Confidence:</b> {inv.get('confidence') or 0.0}</p>
            </div>
            """

        if rem:
            html += f"""
            <div style="background: #1E293B; padding: 10px; border-radius: 6px; margin-bottom: 12px;">
                <h4 style="margin: 0 0 6px 0; color: #34D399;">Remediation Recommendation</h4>
                <p style="margin: 2px 0;"><b>Summary:</b> {rem.get('summary') or 'None'}</p>
                <p style="margin: 2px 0;"><b>Rationale:</b> {rem.get('rationale') or 'None'}</p>
                {f"<p style='margin: 2px 0;'><b>Branch:</b> <code>{rem.get('branch_name')}</code></p>" if rem.get('branch_name') else ""}
            </div>
            """

        if report.safe_actions:
            html += """
            <div style="background: #1E293B; padding: 10px; border-radius: 6px; margin-bottom: 12px;">
                <h4 style="margin: 0 0 6px 0; color: #FBBF24;">Safe Actions</h4>
            """
            for sa in report.safe_actions:
                html += f"""
                <p style="margin: 4px 0; font-size: 12px;">
                    <b>{sa.get('action_type', '').upper()}</b> on <code>{sa.get('target_type')}:{sa.get('target_id')}</code> &mdash;
                    Approval: <b>{sa.get('approval_status')}</b> | Execution: <b>{sa.get('execution_status')}</b>
                </p>
                """
            html += "</div>"

        html += "</div>"
        self.report_text.setHtml(html)

        # Render Timeline tab
        t_lines = []
        if not report.timeline:
            self.timeline_text.setPlainText("No recorded events on timeline.")
        else:
            for ev in report.timeline:
                ts_str = ev.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") if ev.timestamp else "N/A"
                actor_str = f" [{ev.actor}]" if ev.actor else ""
                t_lines.append(f"[{ts_str}] {ev.title}{actor_str}")
                t_lines.append(f"  {ev.description}")
                t_lines.append("")
            self.timeline_text.setPlainText("\n".join(t_lines))

        # Render Operational Memory tab
        if not report.similar_incidents:
            self.memory_text.setPlainText("No similar historical incidents identified in operational memory.")
        else:
            m_lines = []
            for sim in report.similar_incidents:
                m_lines.append(f"=== {sim.title} (Match Score: {sim.similarity_score:.1f}) ===")
                m_lines.append(f"Incident ID: {sim.incident_id} | Service: {sim.service} | Status: {sim.status or 'N/A'}")
                m_lines.append(f"Matched Signals: {', '.join(sim.matched_signals)}")
                m_lines.append(f"Root Cause: {sim.root_cause_hypothesis}")
                if sim.resolution_notes:
                    m_lines.append(f"Resolution / Mitigation Notes: {sim.resolution_notes}")
                m_lines.append("-" * 50)
            self.memory_text.setPlainText("\n".join(m_lines))
