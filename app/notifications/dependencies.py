"""FastAPI dependency injection and lifecycle management for Notifications subsystem."""

from pathlib import Path
import threading
from typing import Optional

from app.notifications.delivery import NotificationDeliveryRuntime
from app.notifications.service import NotificationService
from app.notifications.store import SqliteNotificationStore
from app.projects.dependencies import get_project_store

_lock = threading.RLock()
_notification_store: Optional[SqliteNotificationStore] = None
_notification_service: Optional[NotificationService] = None
_notification_runtime: Optional[NotificationDeliveryRuntime] = None
_custom_notification_db_path: Optional[str] = None


def set_custom_notification_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect notification store to a custom DB path (used by test suites)."""
    global _custom_notification_db_path, _notification_store, _notification_service, _notification_runtime
    with _lock:
        _custom_notification_db_path = db_path
        if _notification_store is not None:
            _notification_store.close()
            _notification_store = None
        _notification_service = None
        _notification_runtime = None


def get_notification_store(db_path: Optional[str] = None) -> SqliteNotificationStore:
    """Provide singleton instance of SqliteNotificationStore."""
    global _notification_store
    with _lock:
        if _notification_store is None:
            resolved_db = db_path or _custom_notification_db_path or "runtime/sentinelops.db"
            _notification_store = SqliteNotificationStore(db_path=resolved_db)
        return _notification_store


def get_notification_runtime() -> NotificationDeliveryRuntime:
    """Provide singleton instance of NotificationDeliveryRuntime."""
    global _notification_runtime
    with _lock:
        if _notification_runtime is None:
            store = get_notification_store()
            _notification_runtime = NotificationDeliveryRuntime(store=store)
        return _notification_runtime


def get_notification_service() -> NotificationService:
    """Provide singleton instance of NotificationService wired with store and runtime."""
    global _notification_service
    with _lock:
        if _notification_service is None:
            store = get_notification_store()
            project_store = get_project_store()
            runtime = get_notification_runtime()
            _notification_service = NotificationService(
                store=store,
                project_store=project_store,
                runtime=runtime,
            )
        return _notification_service


def close_notification_store() -> None:
    """Cleanly checkpoint and close notification store and reset singletons."""
    global _notification_store, _notification_service, _notification_runtime
    with _lock:
        if _notification_store is not None:
            _notification_store.close()
            _notification_store = None
        _notification_service = None
        _notification_runtime = None


def reset_notification_state(db_path: Optional[str] = None) -> None:
    """Reset notification store state strictly for test isolation."""
    global _notification_store, _notification_service, _notification_runtime
    with _lock:
        if _notification_store is not None:
            _notification_store.close()
            _notification_store = None
        _notification_service = None
        _notification_runtime = None
        if db_path is not None:
            set_custom_notification_db_path(db_path)
        store = get_notification_store()
        store.clear()
