"""FastAPI dependency injection and lifecycle management for Safe Action Framework."""

import threading
from typing import List, Optional

from app.actions.executors.connector_test import ConnectorTestExecutor
from app.actions.executors.notification_retry import NotificationRetryExecutor
from app.actions.executors.registry import ActionExecutorRegistry
from app.actions.models import SafeAction
from app.actions.policy import ActionPolicyEngine
from app.actions.service import ActionService
from app.actions.store import SqliteActionStore
from app.connectors.dependencies import get_connector_service, get_connector_store
from app.incidents.dependencies import get_incident_service
from app.notifications.dependencies import get_notification_service, get_notification_store

_lock = threading.RLock()
_action_store: Optional[SqliteActionStore] = None
_action_service: Optional[ActionService] = None
_custom_action_db_path: Optional[str] = None


def set_custom_action_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect action store to a custom DB path (used by test suites)."""
    global _custom_action_db_path, _action_store, _action_service
    with _lock:
        _custom_action_db_path = db_path
        if _action_store is not None:
            _action_store.close()
            _action_store = None
        _action_service = None


def get_action_store(db_path: Optional[str] = None) -> SqliteActionStore:
    """Provide singleton instance of SqliteActionStore."""
    global _action_store
    with _lock:
        if _action_store is None:
            resolved_db = db_path or _custom_action_db_path or "runtime/sentinelops.db"
            _action_store = SqliteActionStore(db_path=resolved_db)
        return _action_store


def close_action_store() -> None:
    """Closes the singleton SqliteActionStore on shutdown."""
    global _action_store, _action_service
    with _lock:
        if _action_store is not None:
            _action_store.close()
            _action_store = None
        _action_service = None


def get_action_executor_registry() -> ActionExecutorRegistry:
    """Creates and populates the ActionExecutorRegistry with allowlisted executors."""
    registry = ActionExecutorRegistry()
    connector_service = get_connector_service()
    notification_service = get_notification_service()

    registry.register(ConnectorTestExecutor(connector_service=connector_service))
    registry.register(NotificationRetryExecutor(notification_service=notification_service))
    return registry


def get_action_policy_engine() -> ActionPolicyEngine:
    """Creates the ActionPolicyEngine."""
    action_store = get_action_store()
    connector_store = get_connector_store()
    notification_store = get_notification_store()
    incident_service = get_incident_service()

    return ActionPolicyEngine(
        action_store=action_store,
        connector_store=connector_store,
        notification_store=notification_store,
        incident_service=incident_service,
    )


def get_action_service() -> ActionService:
    """Provide singleton instance of ActionService wired with store, policy engine, and registry."""
    global _action_service
    with _lock:
        if _action_service is None:
            store = get_action_store()
            policy_engine = get_action_policy_engine()
            registry = get_action_executor_registry()
            _action_service = ActionService(
                store=store,
                policy_engine=policy_engine,
                executor_registry=registry,
            )
        return _action_service


def reconcile_interrupted_actions() -> List[SafeAction]:
    """Triggers startup reconciliation for SafeActions orphaned in executing state."""
    service = get_action_service()
    return service.reconcile_interrupted_executions()
