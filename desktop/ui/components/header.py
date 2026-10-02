"""Header navigation bar component."""

from typing import Callable, List, Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from desktop.api.models import ProjectDTO
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals


class HeaderBar(QWidget):
    """Top application header with brand, project switcher, and health indicator."""

    def __init__(self, on_refresh: Optional[Callable[[], None]] = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HeaderBar")
        self.on_refresh = on_refresh
        self.state = AppState()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(16)

        # Brand / Title
        self.title_label = QLabel("🛡️ SentinelOps Control Center", self)
        self.title_label.setObjectName("AppTitle")
        layout.addWidget(self.title_label)

        # Separator
        sep = QLabel("|", self)
        sep.setStyleSheet("color: #334155; font-size: 16px;")
        layout.addWidget(sep)

        # Project Switcher
        proj_label = QLabel("Project:", self)
        proj_label.setStyleSheet("color: #94A3B8; font-weight: 600;")
        layout.addWidget(proj_label)

        self.project_combo = QComboBox(self)
        self.project_combo.setMinimumWidth(320)
        self.project_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.project_combo.currentIndexChanged.connect(self._on_project_selected)
        layout.addWidget(self.project_combo)

        layout.addStretch()

        # Refresh button
        self.refresh_btn = QPushButton("↻ Refresh", self)
        self.refresh_btn.setStyleSheet(
            "background-color: #334155; color: #F1F5F9; border-radius: 4px; padding: 4px 10px;"
        )
        if self.on_refresh:
            self.refresh_btn.clicked.connect(self.on_refresh)
        layout.addWidget(self.refresh_btn)

        # Connection Pill
        self.connection_pill = QLabel("CONNECTING", self)
        initial_status = AppState().connection_status
        self._update_connection_pill(initial_status)
        layout.addWidget(self.connection_pill)

        # Signal connections
        app_signals.connection_changed.connect(self._update_connection_pill)
        app_signals.projects_updated.connect(self._on_projects_updated)
        app_signals.active_project_changed.connect(self._on_active_project_changed)

    def _update_connection_pill(self, status: str) -> None:
        status_clean = (status or "connecting").lower()
        is_online = (status_clean == "online")
        self.refresh_btn.setEnabled(is_online)
        self.refresh_btn.setToolTip("" if is_online else "Unavailable while offline")

        if is_online:
            self.connection_pill.setText("● ONLINE")
            self.connection_pill.setStyleSheet(
                "background-color: #166534; color: #BBF7D0; border-radius: 12px; "
                "padding: 4px 12px; font-weight: 700; font-size: 11px;"
            )
        elif status_clean == "offline":
            self.connection_pill.setText("● OFFLINE")
            self.connection_pill.setStyleSheet(
                "background-color: #991B1B; color: #FCA5A5; border-radius: 12px; "
                "padding: 4px 12px; font-weight: 700; font-size: 11px;"
            )
        else:
            self.connection_pill.setText("● CONNECTING")
            self.connection_pill.setStyleSheet(
                "background-color: #854D0E; color: #FEF08A; border-radius: 12px; "
                "padding: 4px 12px; font-weight: 700; font-size: 11px;"
            )

    def _on_projects_updated(self, projects: List[ProjectDTO]) -> None:
        self.project_combo.blockSignals(True)
        current_id = self.state.active_project_id
        self.project_combo.clear()
        for i, p in enumerate(projects):
            label = f"{p.name} ({p.project_id})"
            self.project_combo.addItem(label, p.project_id)
            self.project_combo.setItemData(i, label, Qt.ItemDataRole.ToolTipRole)
        if current_id:
            idx = self.project_combo.findData(current_id)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)
        self.project_combo.setToolTip(self.project_combo.currentText())
        self.project_combo.blockSignals(False)

    def _on_active_project_changed(self, project_id: str) -> None:
        idx = self.project_combo.findData(project_id)
        if idx >= 0 and self.project_combo.currentIndex() != idx:
            self.project_combo.blockSignals(True)
            self.project_combo.setCurrentIndex(idx)
            self.project_combo.blockSignals(False)
        self.project_combo.setToolTip(self.project_combo.currentText())

    def _on_project_selected(self, index: int) -> None:
        project_id = self.project_combo.itemData(index)
        if project_id:
            self.project_combo.setToolTip(self.project_combo.currentText())
            self.state.set_active_project(project_id)
