"""FastAPI dependency injection and lifecycle management for Connectors subsystem."""

from pathlib import Path
import threading
from typing import Optional

from app.connectors.poller import ConnectorPollerRuntime
from app.connectors.service import ConnectorService
from app.connectors.store import SqliteConnectorStore
from app.watcher.dependencies import get_watcher_service
from app.watcher.service import WatcherService

_lock = threading.RLock()
_connector_store: Optional[SqliteConnectorStore] = None
_connector_service: Optional[ConnectorService] = None
_connector_runtime: Optional[ConnectorPollerRuntime] = None
_custom_connector_db_path: Optional[str] = None


def set_custom_connector_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect connector store to a custom DB path (used by test suites)."""
    global _custom_connector_db_path, _connector_store, _connector_service, _connector_runtime
    with _lock:
        _custom_connector_db_path = db_path
        if _connector_store is not None:
            _connector_store.close()
            _connector_store = None
        _connector_service = None
        _connector_runtime = None


def get_connector_store(db_path: Optional[str] = None) -> SqliteConnectorStore:
    """Provide singleton instance of SqliteConnectorStore."""
    global _connector_store
    with _lock:
        if _connector_store is None:
            resolved_db = db_path or _custom_connector_db_path or "runtime/sentinelops.db"
            _connector_store = SqliteConnectorStore(db_path=resolved_db)
        return _connector_store


def get_connector_runtime() -> ConnectorPollerRuntime:
    """Provide singleton instance of ConnectorPollerRuntime with concrete store and watcher dependencies."""
    global _connector_runtime
    with _lock:
        if _connector_runtime is None:
            store = get_connector_store()
            watcher = get_watcher_service()
            _connector_runtime = ConnectorPollerRuntime(store=store, watcher_service=watcher)
        return _connector_runtime


def get_connector_service() -> ConnectorService:
    """Provide singleton instance of ConnectorService wired with the shared runtime singleton."""
    global _connector_service
    with _lock:
        if _connector_service is None:
            store = get_connector_store()
            watcher = get_watcher_service()
            runtime = get_connector_runtime()
            _connector_service = ConnectorService(store=store, watcher_service=watcher)
            _connector_service.set_runtime(runtime)
        return _connector_service


def close_connector_store() -> None:
    """Checkpoint and close connector store connection and release singletons."""
    global _connector_store, _connector_service, _connector_runtime
    with _lock:
        if _connector_store is not None:
            _connector_store.close()
            _connector_store = None
        _connector_service = None
        _connector_runtime = None


def reset_connector_state(db_path: Optional[str] = None) -> None:
    """Reset connector store state strictly for test isolation."""
    global _connector_store, _connector_service, _connector_runtime
    with _lock:
        if _connector_store is not None:
            _connector_store.close()
            _connector_store = None
        _connector_service = None
        _connector_runtime = None
        if db_path is not None:
            set_custom_connector_db_path(db_path)
        store = get_connector_store()
        store.clear()
