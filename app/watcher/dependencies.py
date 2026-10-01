"""FastAPI dependencies and singleton instances for Sentinel Watcher."""

from typing import Optional
from app.common.config import config
from app.detection.dependencies import get_detection_engine, reset_detection_state
from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.collectors.file_collector import JsonlFileCollector
from app.watcher.collectors.health_collector import HealthCheckCollector
from app.watcher.service import WatcherService
from app.watcher.storage import SqliteTelemetryStore

_buffer_instance: Optional[RollingTelemetryBuffer] = None
_storage_instance: Optional[SqliteTelemetryStore] = None
_service_instance: Optional[WatcherService] = None


def get_watcher_buffer() -> RollingTelemetryBuffer:
    """Return the shared RollingTelemetryBuffer instance."""
    global _buffer_instance
    if _buffer_instance is None:
        _buffer_instance = RollingTelemetryBuffer(capacity=config.watcher_buffer_capacity)
    return _buffer_instance


def get_watcher_storage() -> SqliteTelemetryStore:
    """Return the shared SqliteTelemetryStore instance."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = SqliteTelemetryStore(db_path=config.watcher_db_path)
    return _storage_instance


def get_watcher_service() -> WatcherService:
    """Return the shared WatcherService orchestrator."""
    global _service_instance
    if _service_instance is None:
        buffer = get_watcher_buffer()
        storage = get_watcher_storage()

        # Instantiate active collectors based on centralized configuration
        file_collector = JsonlFileCollector(
            log_path=config.watcher_log_path,
            project_id=config.watcher_default_project_id,
            service=config.watcher_default_service,
            environment=config.watcher_default_environment,
            poll_interval_seconds=config.watcher_poll_interval_seconds,
        )

        health_collector = HealthCheckCollector(
            health_url=config.watcher_health_check_url,
            project_id=config.watcher_default_project_id,
            service=config.watcher_default_service,
            environment=config.watcher_default_environment,
            probe_interval_seconds=config.watcher_health_check_interval_seconds,
        )

        detection_engine = get_detection_engine()
        _service_instance = WatcherService(
            buffer=buffer,
            storage=storage,
            collectors=[file_collector, health_collector],
            detection_engine=detection_engine,
            retention_hours=config.watcher_db_retention_hours,
            max_storage_events=config.watcher_db_max_events,
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
