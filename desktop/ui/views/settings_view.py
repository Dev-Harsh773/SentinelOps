"""Desktop application settings view."""

import time
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop.api.client import SentinelOpsClient
from desktop.config import DesktopConfig, get_default_config_path
from desktop.state.signals import app_signals
from desktop.workers.task_runner import TaskRunner


class SettingsView(QWidget):
    """View managing desktop client configuration, endpoint testing, and persistence."""

    def __init__(self, config: DesktopConfig, client: SentinelOpsClient, task_runner: TaskRunner, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.client = client
        self.task_runner = task_runner
        self._test_in_flight = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        title = QLabel("Settings & Configuration", self)
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #F8FAFC;")
        main_layout.addWidget(title)

        # Settings Card
        card = QFrame(self)
        card.setProperty("class", "Card")
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(14)

        # Config File Location
        cfg_loc_lbl = QLabel(f"Configuration File: {get_default_config_path()}", card)
        cfg_loc_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        c_layout.addWidget(cfg_loc_lbl)

        # Backend URL row
        url_label = QLabel("Backend API Endpoint:", card)
        url_label.setStyleSheet("color: #CBD5E1; font-weight: 600;")
        c_layout.addWidget(url_label)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit(self.config.backend_url, card)
        self.url_input.setMinimumWidth(350)
        url_row.addWidget(self.url_input)

        self.btn_test = QPushButton("Test Live Connection", card)
        self.btn_test.setStyleSheet("background-color: #334155; color: #F1F5F9; padding: 6px 12px;")
        self.btn_test.clicked.connect(self._test_connection)
        url_row.addWidget(self.btn_test)
        url_row.addStretch()
        c_layout.addLayout(url_row)

        # Polling Cadence Info
        info_lbl = QLabel(
            "Polling Intervals (Configurable):\n"
            f"• Health Check: {self.config.health_poll_interval_seconds}s\n"
            f"• Notification Feed: {self.config.feed_poll_interval_seconds}s\n"
            f"• Incidents: {self.config.incidents_poll_interval_seconds}s\n"
            f"• Connectors: {self.config.connectors_poll_interval_seconds}s",
            card,
        )
        info_lbl.setStyleSheet("color: #94A3B8; font-size: 12px; line-height: 1.4;")
        c_layout.addWidget(info_lbl)

        # Save Button
        save_row = QHBoxLayout()
        self.btn_save = QPushButton("Save Configuration", card)
        self.btn_save.clicked.connect(self._save_config)
        save_row.addWidget(self.btn_save)
        save_row.addStretch()
        c_layout.addLayout(save_row)

        main_layout.addWidget(card)
        main_layout.addStretch()

    def _test_connection(self) -> None:
        if self._test_in_flight:
            return  # Duplicate test in flight guard
        self._test_in_flight = True
        new_url = self.url_input.text().strip().rstrip("/")
        self.btn_test.setEnabled(False)
        self.btn_test.setText("Testing...")

        def worker():
            start = time.perf_counter()
            test_client = SentinelOpsClient(base_url=new_url, timeout=3.0)
            try:
                data = test_client.get_health()
                latency = round((time.perf_counter() - start) * 1000.0, 1)
                return data, latency
            finally:
                test_client.close()

        def on_success(result):
            self._test_in_flight = False
            self.btn_test.setEnabled(True)
            self.btn_test.setText("Test Live Connection")
            data, latency = result
            app_signals.action_succeeded.emit(
                "Connection OK",
                f"Successfully reached {new_url} in {latency}ms (Service: {data.get('service', 'sentinelops')})",
            )

        def on_error(exc: Exception):
            self._test_in_flight = False
            self.btn_test.setEnabled(True)
            self.btn_test.setText("Test Live Connection")
            app_signals.action_failed.emit("Connection Failed", str(exc))

        self.task_runner.run(worker, on_success=on_success, on_error=on_error)

    def _save_config(self) -> None:
        self.config.backend_url = self.url_input.text().strip().rstrip("/")
        try:
            self.config.save()
            app_signals.action_succeeded.emit(
                "Configuration Saved",
                f"Persisted to {get_default_config_path()}",
            )
        except Exception as exc:
            app_signals.action_failed.emit("Save Error", str(exc))
