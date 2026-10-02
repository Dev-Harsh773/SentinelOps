"""Incidents list, filtering, and deep-investigation detail drawer view."""

from typing import List, Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
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
    InvestigationDTO,
    RemediationBranchDTO,
    RemediationDTO,
    RemediationReviewDTO,
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
        """Reset selection and in-flight fetch tracking on project change."""
        self._selected_incident = None
        self._loading_incident_id = None
        self._set_detail_enabled(False)

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

        # Tab 2: Evidence
        self.evidence_text = QTextEdit(self.tabs)
        self.evidence_text.setReadOnly(True)
        self.tabs.addTab(self.evidence_text, "Evidence")

        # Tab 3: Investigation (Read-Only)
        self.investigation_text = QTextEdit(self.tabs)
        self.investigation_text.setReadOnly(True)
        self.tabs.addTab(self.investigation_text, "AI Investigation")

        # Tab 4: Remediation (Read-Only)
        self.remediation_text = QTextEdit(self.tabs)
        self.remediation_text.setReadOnly(True)
        self.tabs.addTab(self.remediation_text, "Remediation")

        p_layout.addWidget(self.tabs)
        self._set_detail_enabled(False)
        return panel

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
        self._all_incidents = incidents
        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self.search_input.text().strip().lower()
        sev_choice = self.sev_filter.currentText().lower()
        status_choice = self.status_filter.currentText().lower()

        filtered = []
        for inc in self._all_incidents:
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

    def _on_row_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._set_detail_enabled(False)
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

    def _render_incident_detail(self, inc: IncidentDTO) -> None:
        self._set_detail_enabled(True)
        self.d_title.setText(inc.title)
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

        # Asynchronously fetch evidence, investigation, remediation
        self._loading_incident_id = inc.id
        self.evidence_text.setPlainText("Loading evidence...")
        self.investigation_text.setPlainText("Loading investigation...")
        self.remediation_text.setPlainText("Loading remediation...")

        def fetch_artifacts():
            ev = self.client.list_incident_evidence(inc.id)
            inv = self.client.get_incident_investigation(inc.id)
            rem = self.client.get_incident_remediation(inc.id)
            rev = self.client.list_remediation_reviews(inc.id) if rem else []
            branch = self.client.get_remediation_branch(inc.id) if rem else None
            return ev, inv, rem, rev, branch

        def on_success(artifacts):
            if (
                self._loading_incident_id != inc.id
                or not self._selected_incident
                or self._selected_incident.id != inc.id
            ):
                return  # Stale response discarded
            ev, inv, rem, rev, branch = artifacts
            self._render_evidence(ev)
            self._render_investigation(inv)
            self._render_remediation(rem, rev, branch)

        def on_error(exc):
            if (
                self._loading_incident_id != inc.id
                or not self._selected_incident
                or self._selected_incident.id != inc.id
            ):
                return  # Stale response discarded
            self.evidence_text.setPlainText(f"Failed to load evidence: {exc}")
            self.investigation_text.setPlainText(f"Failed to load investigation: {exc}")
            self.remediation_text.setPlainText(f"Failed to load remediation: {exc}")

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
