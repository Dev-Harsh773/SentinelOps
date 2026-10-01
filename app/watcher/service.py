"""Orchestration service for Sentinel Watcher subsystem."""

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Dict, List, Optional

from app.common.config import config
from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.collectors.base import TelemetryCollector
from app.watcher.models import CollectorHealth, CollectorStatus, SignalType, TelemetryEvent, WatcherStatus
from app.watcher.schemas import CollectorHealthResponse, WatcherStatusResponse
from app.watcher.storage import SqliteTelemetryStore

logger = logging.getLogger("sentinelops.watcher.service")


class WatcherService:
    """Coordinates active telemetry collectors, the rolling buffer, and local persistence."""

    def __init__(
        self,
        buffer: RollingTelemetryBuffer,
        storage: SqliteTelemetryStore,
        collectors: Optional[List[TelemetryCollector]] = None,
        retention_hours: int = 24,
        max_storage_events: int = 10000,
    ) -> None:
        self._buffer = buffer
        self._storage = storage
        self._collectors: Dict[str, TelemetryCollector] = {}
        if collectors:
            for c in collectors:
                self._collectors[c.name] = c

        self._retention_hours = retention_hours
        self._max_storage_events = max_storage_events

        self._start_time: Optional[float] = None
        self._is_running: bool = False
        self._total_ingested: int = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    def register_collector(self, collector: TelemetryCollector) -> None:
        """Register an active collector."""
        self._collectors[collector.name] = collector

    async def start(self) -> None:
        """Start Watcher and launch all registered collectors."""
        if self._is_running:
            return

        self._start_time = time.perf_counter()
        self._is_running = True
        logger.info("Starting Sentinel Watcher with %d collector(s)", len(self._collectors))

        for collector in self._collectors.values():
            try:
                await collector.start(self.ingest_event)
            except Exception as exc:
                logger.error("Failed to start collector %s: %s", collector.name, exc, exc_info=True)

    async def stop(self) -> None:
        """Stop all collectors, prune storage, and close resources."""
        if not self._is_running:
            return

        logger.info("Stopping Sentinel Watcher")
        self._is_running = False

        # Stop collectors concurrently
        stop_tasks = [collector.stop() for collector in self._collectors.values()]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        # Execute retention pruning on shutdown
        try:
            self._storage.prune(
                max_events=self._max_storage_events,
                retention_hours=self._retention_hours,
            )
        except Exception as exc:
            logger.warning("Error pruning storage during Watcher shutdown: %s", exc)

    async def ingest_event(self, event: TelemetryEvent) -> None:
        """Ingest a validated TelemetryEvent into both rolling buffer and local SQLite store."""
        self._buffer.append(event)
        try:
            self._storage.save(event)
        except Exception as exc:
            logger.error("Error saving event %s to SQLite storage: %s", event.event_id, exc)

        self._total_ingested += 1

    async def ingest_batch(self, events: List[TelemetryEvent]) -> None:
        """Ingest multiple validated TelemetryEvents."""
        for event in events:
            self._buffer.append(event)

        try:
            self._storage.save_batch(events)
        except Exception as exc:
            logger.error("Error saving batch of %d events to SQLite storage: %s", len(events), exc)

        self._total_ingested += len(events)

    def get_status(self) -> WatcherStatusResponse:
        """Return diagnostic health and operational metrics for the Watcher subsystem."""
        uptime = (time.perf_counter() - self._start_time) if self._start_time and self._is_running else 0.0

        collectors_health: Dict[str, CollectorHealthResponse] = {}
        has_degraded = False

        for name, collector in self._collectors.items():
            health = collector.health()
            if health.status in (CollectorStatus.DEGRADED, CollectorStatus.UNHEALTHY):
                has_degraded = True
            collectors_health[name] = CollectorHealthResponse(
                name=health.name,
                collector_type=health.collector_type,
                status=health.status,
                last_event_at=health.last_event_at,
                total_events_collected=health.total_events_collected,
                error_count=health.error_count,
                last_error=health.last_error,
            )

        if not self._is_running:
            status = WatcherStatus.STOPPED
        elif has_degraded:
            status = WatcherStatus.DEGRADED
        else:
            status = WatcherStatus.RUNNING

        storage_count = 0
        try:
            storage_count = self._storage.count()
        except Exception:
            pass

        return WatcherStatusResponse(
            watcher_status=status,
            enabled=config.watcher_enabled,
            uptime_seconds=round(uptime, 2),
            buffer={
                "current_size": self._buffer.size(),
                "capacity": self._buffer.capacity,
            },
            storage={
                "total_stored_events": storage_count,
                "db_path": self._storage.db_path,
            },
            collectors=collectors_health,
        )

    def get_events(
        self,
        limit: int = 50,
        signal_type: Optional[SignalType] = None,
        level: Optional[str] = None,
        service: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[TelemetryEvent]:
        """Query recent events from the in-memory rolling buffer."""
        return self._buffer.get_recent(
            limit=limit,
            signal_type=signal_type,
            level=level,
            service=service,
            project_id=project_id,
        )
