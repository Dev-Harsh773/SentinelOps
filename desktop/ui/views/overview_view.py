"""Operational overview dashboard view."""

from datetime import datetime
from typing import List, Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop.api.models import (
    ConnectorDTO,
    IncidentDTO,
    NotificationDTO,
    WatcherStatusDTO,
)
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.ui.components.status_badge import StatusBadge


class OverviewView(QWidget):
    """Project operational dashboard displaying telemetry, health, and recent alerts."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.state = AppState()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # Title & timestamp header
        header_row = QHBoxLayout()
        self.title_label = QLabel("Operational Overview", self)
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #F8FAFC;")
        header_row.addWidget(self.title_label)

        header_row.addStretch()

        self.timestamp_label = QLabel("Waiting for backend...", self)
        self.timestamp_label.setStyleSheet("color: #64748B; font-size: 11px;")
        header_row.addWidget(self.timestamp_label)
        main_layout.addLayout(header_row)

        # KPI Metrics Cards (Grid)
        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(16)

        self.incidents_card = self._create_card("ACTIVE INCIDENTS", "0", "0 critical")
        self.buffer_card = self._create_card("TELEMETRY BUFFER", "0 / 0", "Watcher enabled")
        self.connectors_card = self._create_card("CONNECTORS", "0 active", "0 healthy")
        self.feed_card = self._create_card("UNREAD IN BATCH", "0", "top 50 loaded")

        metrics_grid.addWidget(self.incidents_card, 0, 0)
        metrics_grid.addWidget(self.buffer_card, 0, 1)
        metrics_grid.addWidget(self.connectors_card, 0, 2)
        metrics_grid.addWidget(self.feed_card, 0, 3)
        main_layout.addLayout(metrics_grid)

        # Active Incidents Summary Section
        inc_section_label = QLabel("Active Incidents", self)
        inc_section_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #CBD5E1; margin-top: 10px;")
        main_layout.addWidget(inc_section_label)

        self.incidents_container = QVBoxLayout()
        self.incidents_container.setSpacing(8)

        self.no_incidents_label = QLabel("No active incidents for this project.", self)
        self.no_incidents_label.setStyleSheet("color: #64748B; padding: 12px;")
        self.incidents_container.addWidget(self.no_incidents_label)

        main_layout.addLayout(self.incidents_container)
        main_layout.addStretch()

        # Connect signals
        app_signals.incidents_updated.connect(self._on_incidents_updated)
        app_signals.notifications_updated.connect(self._on_notifications_updated)
        app_signals.connectors_updated.connect(self._on_connectors_updated)
        app_signals.watcher_status_updated.connect(self._on_watcher_updated)
        app_signals.active_project_changed.connect(self._on_project_changed)

    def _create_card(self, title: str, main_val: str, sub_val: str) -> QFrame:
        card = QFrame(self)
        card.setProperty("class", "Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        t_lbl = QLabel(title, card)
        t_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;")

        m_lbl = QLabel(main_val, card)
        m_lbl.setObjectName("card_val")
        m_lbl.setStyleSheet("font-size: 22px; font-weight: 700; color: #F8FAFC;")

        s_lbl = QLabel(sub_val, card)
        s_lbl.setObjectName("card_sub")
        s_lbl.setStyleSheet("color: #64748B; font-size: 11px;")

        layout.addWidget(t_lbl)
        layout.addWidget(m_lbl)
        layout.addWidget(s_lbl)
        return card

    def _update_card(self, card: QFrame, main_val: str, sub_val: str) -> None:
        m_lbl = card.findChild(QLabel, "card_val")
        s_lbl = card.findChild(QLabel, "card_sub")
        if m_lbl:
            m_lbl.setText(main_val)
        if s_lbl:
            s_lbl.setText(sub_val)

    def _on_project_changed(self, project_id: str) -> None:
        self.title_label.setText(f"Operational Overview — {project_id}")

    def _on_incidents_updated(self, incidents: List[IncidentDTO], ts: Optional[datetime]) -> None:
        if ts:
            self.timestamp_label.setText(f"Session data as of {ts.strftime('%H:%M:%S UTC')}")

        active = [i for i in incidents if i.status in ("open", "investigating")]
        crit = sum(1 for i in active if i.severity == "critical")
        self._update_card(self.incidents_card, str(len(active)), f"{crit} critical")

        # Clear existing rows
        while self.incidents_container.count() > 0:
            item = self.incidents_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not active:
            lbl = QLabel("No active incidents for this project.", self)
            lbl.setStyleSheet("color: #64748B; padding: 12px;")
            self.incidents_container.addWidget(lbl)
        else:
            for inc in active[:4]:  # Show top 4
                row = QFrame(self)
                row.setProperty("class", "Card")
                r_layout = QHBoxLayout(row)
                r_layout.setContentsMargins(12, 8, 12, 8)

                badge_sev = StatusBadge(inc.severity, inc.severity, row)
                badge_stat = StatusBadge(inc.status, inc.status, row)
                title = QLabel(f"<b>{inc.title}</b> — <span style='color: #94A3B8;'>{inc.service} ({inc.environment})</span>", row)

                r_layout.addWidget(badge_sev)
                r_layout.addWidget(badge_stat)
                r_layout.addWidget(title)
                r_layout.addStretch()
                self.incidents_container.addWidget(row)

    def _on_notifications_updated(self, notifications: List[NotificationDTO], ts: Optional[datetime]) -> None:
        unread = sum(1 for n in notifications if n.read_status == "unread")
        self._update_card(self.feed_card, str(unread), f"of {len(notifications)} loaded")

    def _on_connectors_updated(self, connectors: List[ConnectorDTO], ts: Optional[datetime]) -> None:
        healthy = sum(1 for c in connectors if c.health and c.health.operational_status == "healthy")
        self._update_card(self.connectors_card, f"{len(connectors)} total", f"{healthy} healthy")

    def _on_watcher_updated(self, watcher: WatcherStatusDTO) -> None:
        self._update_card(self.buffer_card, f"{watcher.buffer_count} / {watcher.buffer_capacity}", f"Uptime: {int(watcher.uptime_seconds)}s")
