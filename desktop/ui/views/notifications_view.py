"""Interactive notifications feed view with read tracking and retry actions."""

from typing import List, Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop.api.client import SentinelOpsClient
from desktop.api.models import NotificationDTO
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.ui.components.status_badge import StatusBadge
from desktop.workers.task_runner import TaskRunner


class NotificationsView(QWidget):
    """Activity feed displaying project notifications with server-confirmed read tracking."""

    def __init__(self, client: SentinelOpsClient, task_runner: TaskRunner, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.task_runner = task_runner
        self.state = AppState()

        self._all_notifications: List[NotificationDTO] = []
        self._unread_only = False
        self._in_flight_reads: set[str] = set()
        self._in_flight_retries: set[str] = set()
        self._mark_all_in_flight: bool = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # Header Bar
        header_row = QHBoxLayout()
        self.title_label = QLabel("Notifications Feed", self)
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #F8FAFC;")
        header_row.addWidget(self.title_label)

        self.badge_count_label = QLabel("(0 unread in batch)", self)
        self.badge_count_label.setStyleSheet("color: #94A3B8; font-size: 13px; font-weight: 500;")
        header_row.addWidget(self.badge_count_label)

        header_row.addStretch()

        # Filter toggles: All vs Unread
        self.btn_all = QPushButton("All", self)
        self.btn_all.setCheckable(True)
        self.btn_all.setChecked(True)
        self.btn_all.setStyleSheet("padding: 4px 12px;")

        self.btn_unread = QPushButton("Unread Only", self)
        self.btn_unread.setCheckable(True)
        self.btn_unread.setStyleSheet("padding: 4px 12px;")

        filter_group = QButtonGroup(self)
        filter_group.addButton(self.btn_all)
        filter_group.addButton(self.btn_unread)
        filter_group.buttonClicked.connect(self._on_filter_changed)

        header_row.addWidget(self.btn_all)
        header_row.addWidget(self.btn_unread)

        # Mark All Read Button
        self.btn_mark_all = QPushButton("✓ Mark All Read", self)
        self.btn_mark_all.setStyleSheet("background-color: #334155; color: #F1F5F9; padding: 6px 12px;")
        self.btn_mark_all.setEnabled(self.state.is_online())
        self.btn_mark_all.setToolTip("" if self.state.is_online() else "Unavailable while offline")
        self.btn_mark_all.clicked.connect(self._on_mark_all_read_clicked)
        header_row.addWidget(self.btn_mark_all)

        main_layout.addLayout(header_row)

        # Scrollable Feed Container
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background-color: transparent; border: none;")

        self.feed_widget = QWidget()
        self.feed_layout = QVBoxLayout(self.feed_widget)
        self.feed_layout.setContentsMargins(0, 0, 0, 0)
        self.feed_layout.setSpacing(10)

        self.empty_label = QLabel("No notifications for this project.", self.feed_widget)
        self.empty_label.setStyleSheet("color: #64748B; font-size: 14px; padding: 24px;")
        self.feed_layout.addWidget(self.empty_label)
        self.feed_layout.addStretch()

        self.scroll.setWidget(self.feed_widget)
        main_layout.addWidget(self.scroll)

        # Connect signals
        app_signals.notifications_updated.connect(self._on_notifications_updated)
        app_signals.connection_changed.connect(self._on_connection_changed)

    def _on_connection_changed(self, status: str) -> None:
        is_online = (status == "online")
        self.btn_mark_all.setEnabled(is_online)
        self.btn_mark_all.setToolTip("" if is_online else "Unavailable while offline")
        self._render_feed()

    def _on_filter_changed(self) -> None:
        self._unread_only = self.btn_unread.isChecked()
        self._render_feed()

    def _on_notifications_updated(self, notifications: List[NotificationDTO], ts) -> None:
        self._all_notifications = notifications
        unread_in_batch = sum(1 for n in notifications if n.read_status == "unread")
        self.badge_count_label.setText(f"({unread_in_batch} unread in active batch)")
        self._render_feed()

    def _render_feed(self) -> None:
        # Clear existing card widgets
        while self.feed_layout.count() > 0:
            item = self.feed_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        items = [n for n in self._all_notifications if not self._unread_only or n.read_status == "unread"]

        if not items:
            msg = "No unread notifications in active batch." if self._unread_only else "No notifications recorded for this project."
            lbl = QLabel(msg, self.feed_widget)
            lbl.setStyleSheet("color: #64748B; font-size: 14px; padding: 24px;")
            self.feed_layout.addWidget(lbl)
            self.feed_layout.addStretch()
            return

        for notif in items:
            card = self._create_notification_card(notif)
            self.feed_layout.addWidget(card)

        self.feed_layout.addStretch()

    def _create_notification_card(self, notif: NotificationDTO) -> QFrame:
        card = QFrame(self.feed_widget)
        card.setProperty("class", "Card")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(14, 12, 14, 12)
        c_layout.setSpacing(6)

        # Header Row: Badges, Title, Time
        top_row = QHBoxLayout()
        sev_badge = StatusBadge(notif.severity, notif.severity, card)
        top_row.addWidget(sev_badge)

        type_pill = StatusBadge(notif.notification_type, "info", card)
        top_row.addWidget(type_pill)

        # Bold title for unread, normal for read
        weight = "700" if notif.read_status == "unread" else "400"
        title_color = "#F8FAFC" if notif.read_status == "unread" else "#94A3B8"
        title_lbl = QLabel(notif.title, card)
        title_lbl.setStyleSheet(f"font-size: 14px; font-weight: {weight}; color: {title_color};")
        top_row.addWidget(title_lbl)

        top_row.addStretch()

        ts_str = notif.created_at.strftime("%H:%M UTC") if notif.created_at else ""
        time_lbl = QLabel(ts_str, card)
        time_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        top_row.addWidget(time_lbl)
        c_layout.addLayout(top_row)

        # Message
        msg_lbl = QLabel(notif.message, card)
        msg_lbl.setStyleSheet("color: #CBD5E1; font-size: 13px;")
        msg_lbl.setWordWrap(True)
        c_layout.addWidget(msg_lbl)

        # Footer Row: Delivery Channel & Actions
        footer_row = QHBoxLayout()
        channel_lbl = QLabel(f"Channel: {notif.channel} ({notif.delivery_status})", card)
        channel_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        footer_row.addWidget(channel_lbl)

        footer_row.addStretch()

        is_online = self.state.is_online()

        # Mark Read Action (only for unread)
        if notif.read_status == "unread":
            is_reading = notif.notification_id in self._in_flight_reads
            btn_read = QPushButton("Updating..." if is_reading else "✓ Mark Read", card)
            btn_read.setStyleSheet("background-color: #1E293B; color: #94A3B8; border: 1px solid #334155; padding: 2px 8px; font-size: 11px;")
            btn_read.setEnabled(is_online and not is_reading)
            btn_read.setToolTip("Updating notification..." if is_reading else ("" if is_online else "Unavailable while offline"))
            btn_read.clicked.connect(lambda _, nid=notif.notification_id: self._mark_read_server_confirmed(nid))
            footer_row.addWidget(btn_read)

        # Retry Action (only for failed webhook)
        if notif.channel == "webhook" and notif.delivery_status == "failed":
            is_retrying = notif.notification_id in self._in_flight_retries
            btn_retry = QPushButton("Retrying..." if is_retrying else "↻ Retry", card)
            btn_retry.setStyleSheet("background-color: #854D0E; color: #FEF08A; padding: 2px 8px; font-size: 11px;")
            btn_retry.setEnabled(is_online and not is_retrying)
            btn_retry.setToolTip("Retrying delivery..." if is_retrying else ("" if is_online else "Unavailable while offline"))
            btn_retry.clicked.connect(lambda _, nid=notif.notification_id: self._retry_server_confirmed(nid))
            footer_row.addWidget(btn_retry)

        c_layout.addLayout(footer_row)
        return card

    def _mark_read_server_confirmed(self, notification_id: str) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot mark notification as read while offline.")
            return

        if notification_id in self._in_flight_reads:
            return  # Duplicate action guard

        self._in_flight_reads.add(notification_id)
        self._render_feed()

        def worker():
            return self.client.mark_notification_read(notification_id)

        def on_success(updated: NotificationDTO):
            self._in_flight_reads.discard(notification_id)
            self.state.apply_notification_update(updated)
            app_signals.action_succeeded.emit("Notification", "Marked as read.")

        def on_error(exc: Exception):
            self._in_flight_reads.discard(notification_id)
            self._render_feed()
            app_signals.action_failed.emit("Failed to Mark Read", str(exc))

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _retry_server_confirmed(self, notification_id: str) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot retry notification while offline.")
            return

        if notification_id in self._in_flight_retries:
            return  # Duplicate action guard

        self._in_flight_retries.add(notification_id)
        self._render_feed()

        def worker():
            return self.client.retry_notification(notification_id)

        def on_success(updated: NotificationDTO):
            self._in_flight_retries.discard(notification_id)
            self.state.apply_notification_update(updated)
            app_signals.action_succeeded.emit("Retry Initiated", "Notification reset to pending.")

        def on_error(exc: Exception):
            self._in_flight_retries.discard(notification_id)
            self._render_feed()
            app_signals.action_failed.emit("Retry Failed", str(exc))

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _on_mark_all_read_clicked(self) -> None:
        if not self.state.is_online():
            app_signals.action_failed.emit("Action Blocked", "Cannot mark all read while offline.")
            return

        if self._mark_all_in_flight:
            return  # Guard duplicate mark-all action

        active_id = self.state.active_project_id
        if not active_id:
            return

        reply = QMessageBox.question(
            self,
            "Mark All Read",
            f"Mark all notifications as read for project '{active_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._mark_all_in_flight = True
        self.btn_mark_all.setEnabled(False)
        self.btn_mark_all.setText("Marking...")

        def worker():
            return self.client.mark_all_notifications_read(active_id)

        def on_success(result):
            self._mark_all_in_flight = False
            self.btn_mark_all.setEnabled(self.state.is_online())
            self.btn_mark_all.setText("✓ Mark All Read")
            # Re-fetch notifications to get authoritative updated list
            try:
                updated_list = self.client.list_notifications(project_id=active_id, limit=50, offset=0)
                self.state.set_notifications(active_id, updated_list)
            except Exception:
                pass
            app_signals.action_succeeded.emit("Mark All Read", f"Marked {result.get('marked_read_count', 0)} notifications as read.")

        def on_error(exc: Exception):
            self._mark_all_in_flight = False
            self.btn_mark_all.setEnabled(self.state.is_online())
            self.btn_mark_all.setText("✓ Mark All Read")
            app_signals.action_failed.emit("Mark All Read Failed", str(exc))

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)
