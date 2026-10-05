"""Main application window for SentinelOps Windows Control Center."""

from datetime import datetime, timezone
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop.api.client import SentinelOpsClient
from desktop.config import DesktopConfig
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals
from desktop.ui.components.header import HeaderBar
from desktop.ui.components.sidebar import SidebarRail
from desktop.ui.components.toast import ToastNotification
from desktop.ui.styles import DARK_THEME_QSS
from desktop.ui.views.connectors_view import ConnectorsView
from desktop.ui.views.incidents_view import IncidentsView
from desktop.ui.views.knowledge_view import KnowledgeView
from desktop.ui.views.notifications_view import NotificationsView
from desktop.ui.views.overview_view import OverviewView
from desktop.ui.views.settings_view import SettingsView
from desktop.workers.poller import BackgroundPoller
from desktop.workers.task_runner import TaskRunner


class MainWindow(QMainWindow):
    """Primary desktop shell window."""

    def __init__(self, config: DesktopConfig, client: SentinelOpsClient) -> None:
        super().__init__()
        self.config = config
        self.client = client
        self.state = AppState()
        self.task_runner = TaskRunner(max_threads=4)
        self.poller = BackgroundPoller(client=self.client, config=self.config)

        self.setWindowTitle("SentinelOps Control Center")
        self.resize(self.config.window_width, self.config.window_height)
        self.setStyleSheet(DARK_THEME_QSS)

        # Central Root Container
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Offline Banner (hidden by default)
        self.offline_banner = QLabel(
            "⚠️ Backend disconnected. Displaying cached session data (non-authoritative). Reconnecting...",
            central,
        )
        self.offline_banner.setObjectName("OfflineBanner")
        self.offline_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.offline_banner.hide()
        root_layout.addWidget(self.offline_banner)

        # 2. Header Bar
        self.header = HeaderBar(on_refresh=self._on_global_refresh, parent=central)
        root_layout.addWidget(self.header)

        # 3. Main Workspace: Sidebar + Stacked Views
        body = QWidget(central)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = SidebarRail(body)
        self.sidebar.navigation_requested.connect(self._on_navigation)
        body_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget(body)
        self.overview_view = OverviewView(self.stack)
        self.incidents_view = IncidentsView(client=self.client, task_runner=self.task_runner, parent=self.stack)
        self.notifications_view = NotificationsView(client=self.client, task_runner=self.task_runner, parent=self.stack)
        self.connectors_view = ConnectorsView(client=self.client, task_runner=self.task_runner, parent=self.stack)
        self.knowledge_view = KnowledgeView(client=self.client, task_runner=self.task_runner, parent=self.stack)
        self.settings_view = SettingsView(config=self.config, client=self.client, task_runner=self.task_runner, parent=self.stack)

        self.stack.addWidget(self.overview_view)        # 0
        self.stack.addWidget(self.incidents_view)       # 1
        self.stack.addWidget(self.notifications_view)   # 2
        self.stack.addWidget(self.connectors_view)      # 3
        self.stack.addWidget(self.knowledge_view)       # 4
        self.stack.addWidget(self.settings_view)        # 5

        body_layout.addWidget(self.stack)
        root_layout.addWidget(body)

        # 4. Toast Notification Overlay
        self.toast = ToastNotification(self)

        # Connect event bus signals
        app_signals.connection_changed.connect(self._on_connection_changed)
        app_signals.action_succeeded.connect(lambda title, msg: self.toast.show_message(f"✓ {title}: {msg}", is_error=False))
        app_signals.action_failed.connect(lambda title, msg: self.toast.show_message(f"✕ {title}: {msg}", is_error=True))
        app_signals.active_project_changed.connect(self._on_active_project_changed)

        # Start background polling
        self.poller.start()

    def _on_global_refresh(self) -> None:
        """Trigger immediate background poller refresh AND invoke active view refresh."""
        self.poller.trigger_immediate_refresh()
        active = self.stack.currentWidget()
        if hasattr(active, "refresh") and callable(active.refresh):
            active.refresh()

    def _on_navigation(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        active = self.stack.widget(index)
        if hasattr(active, "on_view_activated") and callable(active.on_view_activated):
            active.on_view_activated()

    def _on_active_project_changed(self, project_id: str) -> None:
        self.setWindowTitle(f"SentinelOps Control Center — {project_id}")

    def _on_connection_changed(self, status: str) -> None:
        if status == "offline":
            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            self.offline_banner.setText(
                f"⚠️ Backend disconnected. Displaying cached session data as of {now_str} (non-authoritative). Reconnecting..."
            )
            self.offline_banner.show()
        else:
            self.offline_banner.hide()

    def closeEvent(self, event) -> None:
        """Binding correction 8: Terminate all worker threads and exit cleanly."""
        self.poller.stop()
        self.poller.wait(2000)
        self.task_runner.stop(1000)
        self.client.close()
        event.accept()
        QApplication.instance().quit()
