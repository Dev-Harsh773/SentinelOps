"""Project workspace and knowledge base status view."""

from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop.api.client import SentinelOpsClient
from desktop.api.models import ProjectKnowledgeDTO
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.ui.components.status_badge import StatusBadge
from desktop.workers.task_runner import TaskRunner


class KnowledgeView(QWidget):
    """View displaying project knowledge base metadata, routes, and reindex trigger."""

    def __init__(self, client: SentinelOpsClient, task_runner: TaskRunner, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.task_runner = task_runner
        self.state = AppState()
        self._reindexing_projects: set[str] = set()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(14)

        # Header
        header_row = QHBoxLayout()
        self.title_lbl = QLabel("Project Knowledge Base", self)
        self.title_lbl.setStyleSheet("font-size: 20px; font-weight: 700; color: #F8FAFC;")
        header_row.addWidget(self.title_lbl)

        header_row.addStretch()

        # Reindex Action Button
        self.btn_reindex = QPushButton("↻ Reindex Workspace", self)
        self.btn_reindex.setStyleSheet("background-color: #2563EB; color: #FFFFFF; padding: 6px 14px;")
        self.btn_reindex.setEnabled(self.state.is_online())
        self.btn_reindex.setToolTip("" if self.state.is_online() else "Unavailable while offline")
        self.btn_reindex.clicked.connect(self._on_reindex_clicked)
        header_row.addWidget(self.btn_reindex)

        main_layout.addLayout(header_row)

        # Overview Card: Path, Git Branch, Indexed Timestamp
        meta_card = QFrame(self)
        meta_card.setProperty("class", "Card")
        meta_layout = QGridLayout(meta_card)
        meta_layout.setSpacing(10)

        self.path_lbl = QLabel("Workspace: -", meta_card)
        self.branch_lbl = QLabel("Git Branch: -", meta_card)
        self.indexed_lbl = QLabel("Last Indexed: -", meta_card)
        self.files_lbl = QLabel("Files: 0 | Chunks: 0", meta_card)

        self.path_lbl.setStyleSheet("color: #CBD5E1; font-size: 13px;")
        self.branch_lbl.setStyleSheet("color: #CBD5E1; font-size: 13px;")
        self.indexed_lbl.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.files_lbl.setStyleSheet("color: #60A5FA; font-weight: 600; font-size: 14px;")

        meta_layout.addWidget(self.path_lbl, 0, 0)
        meta_layout.addWidget(self.branch_lbl, 0, 1)
        meta_layout.addWidget(self.files_lbl, 1, 0)
        meta_layout.addWidget(self.indexed_lbl, 1, 1)

        main_layout.addWidget(meta_card)

        # Detected HTTP Routes Table
        routes_title = QLabel("Detected HTTP Routes", self)
        routes_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #CBD5E1;")
        main_layout.addWidget(routes_title)

        self.routes_table = QTableWidget(self)
        self.routes_table.setColumnCount(4)
        self.routes_table.setHorizontalHeaderLabels(["Method", "Path", "File", "Handler"])
        self.routes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.routes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        main_layout.addWidget(self.routes_table)

        # Signals
        app_signals.knowledge_updated.connect(self._on_knowledge_updated)
        app_signals.active_project_changed.connect(self._on_project_changed)
        app_signals.connection_changed.connect(self._on_connection_changed)

    def _update_reindex_button_state(self) -> None:
        """Update reindex button presentation based on active project in-flight status and connection."""
        active_id = self.state.active_project_id
        is_reindexing = (active_id is not None and active_id in self._reindexing_projects)
        is_online = self.state.is_online()

        if is_reindexing:
            self.btn_reindex.setEnabled(False)
            self.btn_reindex.setText("Reindexing...")
            self.btn_reindex.setToolTip("Workspace reindex in progress...")
        else:
            self.btn_reindex.setEnabled(is_online)
            self.btn_reindex.setText("↻ Reindex Workspace")
            self.btn_reindex.setToolTip("" if is_online else "Unavailable while offline")

    def _on_connection_changed(self, status: str) -> None:
        self._update_reindex_button_state()

    def _on_project_changed(self, project_id: str) -> None:
        self.title_lbl.setText(f"Project Knowledge Base — {project_id}")
        self._update_reindex_button_state()

        # Fetch knowledge asynchronously for newly selected project
        def worker():
            return self.client.get_project_knowledge(project_id)

        def on_success(data):
            if self.state.active_project_id == project_id:
                self.state.set_knowledge(project_id, data)
            else:
                self.state.cached_knowledge[project_id] = (data, datetime.now(timezone.utc))

        def on_error(exc):
            pass

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _on_knowledge_updated(self, know: ProjectKnowledgeDTO, ts) -> None:
        # Match against current project details for workspace path
        proj = next((p for p in self.state.projects if p.project_id == know.project_id), None)
        path = proj.workspace_path if proj else "-"

        self.path_lbl.setText(f"Workspace: {path}")
        branch = know.current_branch or "non-git"
        self.branch_lbl.setText(f"Git Branch: {branch} (HEAD: {know.current_head[:7] if know.current_head else '-'})")
        self.files_lbl.setText(f"Files: {know.files_count} | Chunks: {know.chunks_count}")

        idx_str = know.indexed_at.strftime("%Y-%m-%d %H:%M UTC") if know.indexed_at else "Not indexed"
        self.indexed_lbl.setText(f"Last Indexed: {idx_str} (Version: {know.index_version})")

        # Populate routes
        self.routes_table.setRowCount(len(know.routes))
        for row, r in enumerate(know.routes):
            m_badge = StatusBadge(r.method, "info")
            self.routes_table.setCellWidget(row, 0, m_badge)
            self.routes_table.setItem(row, 1, QTableWidgetItem(r.path))
            self.routes_table.setItem(row, 2, QTableWidgetItem(r.file_path))
            self.routes_table.setItem(row, 3, QTableWidgetItem(f"{r.function_name}:{r.start_line}"))

    def _on_reindex_clicked(self) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot reindex workspace while offline.")
            return

        project_id = self.state.active_project_id
        if not project_id:
            return

        if project_id in self._reindexing_projects:
            return  # Duplicate reindex in flight guard

        reply = QMessageBox.question(
            self,
            "Reindex Workspace",
            f"Refresh AST index and knowledge base for project '{project_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._reindexing_projects.add(project_id)
        self._update_reindex_button_state()

        def worker():
            return self.client.reindex_project(project_id)

        def on_success(updated_knowledge: ProjectKnowledgeDTO):
            self._reindexing_projects.discard(project_id)
            self._update_reindex_button_state()
            if self.state.active_project_id == project_id:
                self.state.set_knowledge(project_id, updated_knowledge)
            app_signals.action_succeeded.emit(
                "Reindex Complete",
                f"Knowledge base refreshed: {updated_knowledge.files_count} files, {updated_knowledge.chunks_count} chunks.",
            )

        def on_error(exc: Exception):
            self._reindexing_projects.discard(project_id)
            self._update_reindex_button_state()
            app_signals.action_failed.emit("Reindex Failed", str(exc))

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)
