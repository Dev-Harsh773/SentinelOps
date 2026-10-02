"""Unit tests for desktop in-memory session state management."""

from datetime import datetime, timezone
from desktop.api.models import IncidentDTO, NotificationDTO, ProjectDTO
from desktop.state.app_state import AppState
from desktop.state.signals import app_signals


def test_app_state_singleton_and_defaults():
    state = AppState()
    assert state is AppState()
    assert state.connection_status in ("online", "offline", "connecting")


def test_app_state_project_selection_and_caching():
    state = AppState()
    projects = [
        ProjectDTO(project_id="p-1", name="Project 1", workspace_path="/p1", status="ready"),
        ProjectDTO(project_id="p-2", name="Project 2", workspace_path="/p2", status="ready"),
    ]
    state.set_projects(projects)
    assert state.active_project_id == "p-1"

    # Switch project
    state.set_active_project("p-2")
    assert state.active_project_id == "p-2"


def test_app_state_incidents_filtering():
    state = AppState()
    now = datetime.now(timezone.utc)
    incidents = [
        IncidentDTO(id="i-1", title="Inc 1", summary="S1", severity="low", status="open", service="s", environment="e", project_id="p-1"),
        IncidentDTO(id="i-2", title="Inc 2", summary="S2", severity="high", status="open", service="s", environment="e", project_id="p-2"),
    ]
    state.set_active_project("p-1")
    state.set_incidents_from_all(incidents)

    cached_p1, _ = state.cached_incidents.get("p-1", ([], None))
    cached_p2, _ = state.cached_incidents.get("p-2", ([], None))

    assert len(cached_p1) == 1
    assert cached_p1[0].id == "i-1"
    assert len(cached_p2) == 1
    assert cached_p2[0].id == "i-2"


def test_app_state_batch_unread_count_derivation():
    state = AppState()
    notifs = [
        NotificationDTO(notification_id="n-1", project_id="p-1", read_status="unread"),
        NotificationDTO(notification_id="n-2", project_id="p-1", read_status="unread"),
        NotificationDTO(notification_id="n-3", project_id="p-1", read_status="read"),
    ]
    state.set_active_project("p-1")
    state.set_notifications("p-1", notifs)

    # Binding correction 2: unread in active batch is 2
    assert state.batch_unread_count == 2

    # Server confirmed update
    updated_n1 = NotificationDTO(notification_id="n-1", project_id="p-1", read_status="read")
    state.apply_notification_update(updated_n1)

    assert state.batch_unread_count == 1
