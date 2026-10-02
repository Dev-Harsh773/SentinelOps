"""Central Qt Signal bus for decoupled cross-component communication."""

from PyQt6.QtCore import QObject, pyqtSignal


class AppSignals(QObject):
    """Event bus emitting thread-safe notifications across the UI."""

    # Connection liveness: "online", "offline", "connecting"
    connection_changed = pyqtSignal(str)

    # Project selection
    active_project_changed = pyqtSignal(str)
    projects_updated = pyqtSignal(list)

    # Domain models with timestamp: (data_list, fetch_datetime)
    incidents_updated = pyqtSignal(list, object)
    notifications_updated = pyqtSignal(list, object)
    connectors_updated = pyqtSignal(list, object)
    knowledge_updated = pyqtSignal(object, object)
    watcher_status_updated = pyqtSignal(object)

    # Binding correction 2: Unread count in active loaded batch
    batch_unread_count_updated = pyqtSignal(int)

    # Toast / feedback notices
    action_succeeded = pyqtSignal(str, str)
    action_failed = pyqtSignal(str, str)


app_signals = AppSignals()
