"""Desktop application main content views."""

from desktop.ui.views.connectors_view import ConnectorsView
from desktop.ui.views.incidents_view import IncidentsView
from desktop.ui.views.knowledge_view import KnowledgeView
from desktop.ui.views.notifications_view import NotificationsView
from desktop.ui.views.overview_view import OverviewView
from desktop.ui.views.settings_view import SettingsView

__all__ = [
    "OverviewView",
    "IncidentsView",
    "NotificationsView",
    "ConnectorsView",
    "KnowledgeView",
    "SettingsView",
]
