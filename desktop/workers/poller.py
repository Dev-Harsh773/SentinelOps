"""Background polling worker for periodic health, telemetry, and notification monitoring."""

import time
from PyQt6.QtCore import QThread

from desktop.api.client import SentinelOpsClient
from desktop.api.exceptions import BackendUnavailableError
from desktop.config import DesktopConfig
from desktop.state.app_state import AppState


class BackgroundPoller(QThread):
    """Dedicated background thread polling SentinelOps backend at regular intervals."""

    def __init__(self, client: SentinelOpsClient, config: DesktopConfig) -> None:
        super().__init__()
        self.client = client
        self.config = config
        self.state = AppState()
        self._running = True

        # Polling tracking
        self._last_health = 0.0
        self._last_feed = 0.0
        self._last_incidents = 0.0
        self._last_connectors = 0.0
        self._last_projects = 0.0

        # Backoff multiplier on failure
        self._backoff = 1.0

    def stop(self) -> None:
        """Signal poller loop to stop."""
        self._running = False

    def trigger_immediate_refresh(self) -> None:
        """Force next poll loop cycle to refresh all streams immediately."""
        self._last_health = 0.0
        self._last_feed = 0.0
        self._last_incidents = 0.0
        self._last_connectors = 0.0
        self._last_projects = 0.0

    def run(self) -> None:
        """Main polling loop running on background thread."""
        while self._running:
            now = time.time()
            try:
                # 1. Health check & Watcher status
                if now - self._last_health >= (self.config.health_poll_interval_seconds * self._backoff):
                    self._poll_health()
                    self._last_health = now

                # 2. Projects list
                if now - self._last_projects >= (30.0 * self._backoff):
                    self._poll_projects()
                    self._last_projects = now

                # 3. Active project scoped streams
                active_id = self.state.active_project_id
                if active_id and self.state.connection_status == "online":
                    # Combined notifications feed + batch unread calculation
                    if now - self._last_feed >= self.config.feed_poll_interval_seconds:
                        self._poll_feed(active_id)
                        self._last_feed = now

                    # Incidents list
                    if now - self._last_incidents >= self.config.incidents_poll_interval_seconds:
                        self._poll_incidents()
                        self._last_incidents = now

                    # Connectors list
                    if now - self._last_connectors >= self.config.connectors_poll_interval_seconds:
                        self._poll_connectors(active_id)
                        self._last_connectors = now

                # Success -> reset backoff
                if self.state.connection_status == "online":
                    self._backoff = 1.0

            except BackendUnavailableError:
                self.state.set_connection_status("offline")
                # Exponential backoff up to 6x (e.g. 60s max)
                self._backoff = min(6.0, self._backoff * 1.5)
            except Exception:
                pass

            # Sleep in short increments to allow rapid clean thread shutdown
            for _ in range(10):
                if not self._running:
                    break
                time.sleep(0.1)

    def _poll_health(self) -> None:
        self.client.get_health()
        self.state.set_connection_status("online")
        try:
            watcher = self.client.get_watcher_status()
            self.state.set_watcher_status(watcher)
        except Exception:
            pass

    def _poll_projects(self) -> None:
        projects = self.client.list_projects()
        self.state.set_projects(projects)

    def _poll_feed(self, project_id: str) -> None:
        # Single-stream: load top 50 notifications, derive batch unread
        notifs = self.client.list_notifications(project_id=project_id, limit=50, offset=0)
        self.state.set_notifications(project_id, notifs)

    def _poll_incidents(self) -> None:
        all_incidents = self.client.list_incidents()
        self.state.set_incidents_from_all(all_incidents)

    def _poll_connectors(self, project_id: str) -> None:
        connectors = self.client.list_connectors(project_id=project_id)
        self.state.set_connectors(project_id, connectors)
