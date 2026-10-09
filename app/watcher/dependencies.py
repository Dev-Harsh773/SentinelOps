"""FastAPI dependencies and singleton instances for Sentinel Watcher."""

from typing import Optional
from app.common import config as config_module
from app.correlation.dependencies import reset_correlation_state
from app.detection.dependencies import get_detection_engine, reset_detection_state
from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.collectors.file_collector import JsonlFileCollector
from app.watcher.collectors.health_collector import HealthCheckCollector
from app.watcher.service import WatcherService
from app.watcher.storage import SqliteTelemetryStore

_buffer_instance: Optional[RollingTelemetryBuffer] = None
_storage_instance: Optional[SqliteTelemetryStore] = None
_service_instance: Optional[WatcherService] = None
_custom_watcher_db_path: Optional[str] = None


def set_custom_watcher_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect watcher storage to a custom DB path for test isolation."""
    global _custom_watcher_db_path, _storage_instance
    _custom_watcher_db_path = db_path
    if _storage_instance is not None:
        _storage_instance.close()
        _storage_instance = None


def get_watcher_buffer() -> RollingTelemetryBuffer:
    """Return the shared RollingTelemetryBuffer instance."""
    global _buffer_instance
    if _buffer_instance is None:
        _buffer_instance = RollingTelemetryBuffer(capacity=config_module.config.watcher_buffer_capacity)
    return _buffer_instance


def get_watcher_storage() -> SqliteTelemetryStore:
    """Return the shared SqliteTelemetryStore instance."""
    global _storage_instance
    if _storage_instance is None:
        db_path = _custom_watcher_db_path or config_module.config.watcher_db_path
        _storage_instance = SqliteTelemetryStore(db_path=db_path)
    return _storage_instance


def get_watcher_service() -> WatcherService:
    """Return the shared WatcherService orchestrator."""
    global _service_instance
    if _service_instance is None:
        buffer = get_watcher_buffer()
        storage = get_watcher_storage()
        cfg = config_module.config

        # Instantiate active collectors based on centralized configuration
        file_collector = JsonlFileCollector(
            log_path=cfg.watcher_log_path,
            project_id=cfg.watcher_default_project_id,
            service=cfg.watcher_default_service,
            environment=cfg.watcher_default_environment,
            poll_interval_seconds=cfg.watcher_poll_interval_seconds,
        )

        health_collector = HealthCheckCollector(
            health_url=cfg.watcher_health_check_url,
            project_id=cfg.watcher_default_project_id,
            service=cfg.watcher_default_service,
            environment=cfg.watcher_default_environment,
            probe_interval_seconds=cfg.watcher_health_check_interval_seconds,
        )

        detection_engine = get_detection_engine()
        _service_instance = WatcherService(
            buffer=buffer,
            storage=storage,
            collectors=[file_collector, health_collector],
            detection_engine=detection_engine,
            retention_hours=cfg.watcher_db_retention_hours,
            max_storage_events=cfg.watcher_db_max_events,
        )

    return _service_instance


def reset_watcher_state() -> None:
    """Reset Watcher and Detection singletons for test isolation."""
    global _buffer_instance, _storage_instance, _service_instance
    if _buffer_instance:
        _buffer_instance.clear()
    _buffer_instance = None

    if _storage_instance:
        _storage_instance.close()
    _storage_instance = None

    _service_instance = None
    reset_detection_state()
    reset_correlation_state()
