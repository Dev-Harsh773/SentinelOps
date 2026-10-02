"""In-memory session state manager.

Maintains cached domain entities, active project selection, and connection status
for the duration of the application session. Zero disk caching of API payloads.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from desktop.api.models import (
    ConnectorDTO,
    IncidentDTO,
    NotificationDTO,
    ProjectDTO,
    ProjectKnowledgeDTO,
    WatcherStatusDTO,
)
from desktop.state.signals import app_signals


class AppState:
    """Singleton holding in-memory desktop session state."""

    _instance: Optional["AppState"] = None

    def __new__(cls) -> "AppState":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_state()
        return cls._instance

    def _init_state(self) -> None:
        self.connection_status: str = "connecting"
        self.active_project_id: Optional[str] = None
        self.projects: List[ProjectDTO] = []

        # In-memory session caches: project_id -> (data, fetch_timestamp)
        self.cached_incidents: Dict[str, Tuple[List[IncidentDTO], datetime]] = {}
        self.cached_notifications: Dict[str, Tuple[List[NotificationDTO], datetime]] = {}
        self.cached_connectors: Dict[str, Tuple[List[ConnectorDTO], datetime]] = {}
        self.cached_knowledge: Dict[str, Tuple[ProjectKnowledgeDTO, datetime]] = {}

        # Unread count in the currently loaded active batch
        self.batch_unread_count: int = 0
        self.last_watcher_status: Optional[WatcherStatusDTO] = None

    def is_online(self) -> bool:
        return self.connection_status == "online"

    def set_connection_status(self, status: str) -> None:
        if self.connection_status != status:
            self.connection_status = status
            app_signals.connection_changed.emit(status)

    def set_projects(self, projects: List[ProjectDTO]) -> None:
        self.projects = list(projects)
        app_signals.projects_updated.emit(self.projects)
        if not self.active_project_id and self.projects:
            self.set_active_project(self.projects[0].project_id)

    def set_active_project(self, project_id: str) -> None:
        if self.active_project_id != project_id:
            self.active_project_id = project_id
            app_signals.active_project_changed.emit(project_id)

            # Re-emit cached data if available for immediate responsiveness
            if project_id in self.cached_incidents:
                data, ts = self.cached_incidents[project_id]
                app_signals.incidents_updated.emit(data, ts)
            if project_id in self.cached_notifications:
                notifs, ts = self.cached_notifications[project_id]
                app_signals.notifications_updated.emit(notifs, ts)
                self._update_batch_unread(notifs)
            if project_id in self.cached_connectors:
                conns, ts = self.cached_connectors[project_id]
                app_signals.connectors_updated.emit(conns, ts)
            if project_id in self.cached_knowledge:
                know, ts = self.cached_knowledge[project_id]
                app_signals.knowledge_updated.emit(know, ts)

    def set_incidents_from_all(self, all_incidents: List[IncidentDTO]) -> None:
        """Filter incoming full incidents list by active project and cache."""
        now = datetime.now(timezone.utc)
        by_project: Dict[str, List[IncidentDTO]] = {}
        for inc in all_incidents:
            by_project.setdefault(inc.project_id, []).append(inc)

        for proj in self.projects:
            self.cached_incidents[proj.project_id] = (by_project.get(proj.project_id, []), now)

        if self.active_project_id:
            current_list = by_project.get(self.active_project_id, [])
            self.cached_incidents[self.active_project_id] = (current_list, now)
            app_signals.incidents_updated.emit(current_list, now)

    def set_notifications(self, project_id: str, notifications: List[NotificationDTO]) -> None:
        now = datetime.now(timezone.utc)
        self.cached_notifications[project_id] = (notifications, now)
        if self.active_project_id == project_id:
            app_signals.notifications_updated.emit(notifications, now)
            self._update_batch_unread(notifications)

    def apply_notification_update(self, updated: NotificationDTO) -> None:
        """Apply server-confirmed single notification update."""
        proj_id = updated.project_id
        if proj_id in self.cached_notifications:
            items, ts = self.cached_notifications[proj_id]
            new_items = [updated if n.notification_id == updated.notification_id else n for n in items]
            self.cached_notifications[proj_id] = (new_items, ts)
            if self.active_project_id == proj_id:
                app_signals.notifications_updated.emit(new_items, ts)
                self._update_batch_unread(new_items)

    def set_connectors(self, project_id: str, connectors: List[ConnectorDTO]) -> None:
        now = datetime.now(timezone.utc)
        self.cached_connectors[project_id] = (connectors, now)
        if self.active_project_id == project_id:
            app_signals.connectors_updated.emit(connectors, now)

    def set_knowledge(self, project_id: str, knowledge: ProjectKnowledgeDTO) -> None:
        now = datetime.now(timezone.utc)
        self.cached_knowledge[project_id] = (knowledge, now)
        if self.active_project_id == project_id:
            app_signals.knowledge_updated.emit(knowledge, now)

    def set_watcher_status(self, status: WatcherStatusDTO) -> None:
        self.last_watcher_status = status
        app_signals.watcher_status_updated.emit(status)

    def _update_batch_unread(self, notifications: List[NotificationDTO]) -> None:
        """Derive unread count for the active batch and notify."""
        count = sum(1 for n in notifications if n.read_status == "unread")
        self.batch_unread_count = count
        app_signals.batch_unread_count_updated.emit(count)
