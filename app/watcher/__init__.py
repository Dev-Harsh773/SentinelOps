"""Sentinel Watcher subsystem package.

Exports core models, collector interfaces, and service accessors for continuous
runtime telemetry observation, buffering, and local persistence.
"""

from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.collectors.base import TelemetryCollector
from app.watcher.collectors.file_collector import JsonlFileCollector
from app.watcher.collectors.health_collector import HealthCheckCollector
from app.watcher.dependencies import (
    get_watcher_buffer,
    get_watcher_service,
    get_watcher_storage,
    reset_watcher_state,
)
from app.watcher.models import (
    CollectorHealth,
    CollectorStatus,
    CollectorType,
    SignalType,
    TelemetryEvent,
    WatcherStatus,
)
from app.watcher.routes import router as watcher_router
from app.watcher.service import WatcherService
from app.watcher.storage import SqliteTelemetryStore

__all__ = [
    "CollectorHealth",
    "CollectorStatus",
    "CollectorType",
    "HealthCheckCollector",
    "JsonlFileCollector",
    "RollingTelemetryBuffer",
    "SignalType",
    "SqliteTelemetryStore",
    "TelemetryCollector",
    "TelemetryEvent",
    "WatcherService",
    "WatcherStatus",
    "get_watcher_buffer",
    "get_watcher_service",
    "get_watcher_storage",
    "reset_watcher_state",
    "watcher_router",
]
