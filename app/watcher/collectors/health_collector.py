"""Synthetic health check probe collector for Sentinel Watcher.

Periodically queries a configured target service HTTP health endpoint,
emitting structured TelemetryEvent records with SignalType.HEALTH.
Preserves underlying failure types (timeout, connection_refused, http_status_failure)
and HTTP status codes in metadata.
"""

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional
import uuid

import httpx

from app.watcher.collectors.base import TelemetryCollector
from app.watcher.models import CollectorHealth, CollectorStatus, CollectorType, SignalType, TelemetryEvent

logger = logging.getLogger("sentinelops.watcher.collectors.health")


class HealthCheckCollector(TelemetryCollector):
    """Active background observer periodically probing an HTTP health endpoint."""

    def __init__(
        self,
        health_url: str,
        project_id: str,
        service: str,
        environment: str,
        probe_interval_seconds: float = 5.0,
        timeout_seconds: float = 2.0,
        name: str = "health_check_collector",
    ) -> None:
        self._health_url = health_url
        self._project_id = project_id
        self._service = service
        self._environment = environment
        self._probe_interval = probe_interval_seconds
        self._timeout = timeout_seconds
        self._name = name

        self._is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._emit_callback: Optional[Callable[[TelemetryEvent], Awaitable[None]]] = None
        self._client: Optional[httpx.AsyncClient] = None

        self._status = CollectorStatus.STOPPED
        self._last_event_at: Optional[datetime] = None
        self._total_events_collected: int = 0
        self._error_count: int = 0
        self._last_error: Optional[str] = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def collector_type(self) -> CollectorType:
        return CollectorType.HEALTH_CHECK

    @property
    def health_url(self) -> str:
        return self._health_url

    def health(self) -> CollectorHealth:
        return CollectorHealth(
            name=self._name,
            collector_type=self.collector_type,
            status=self._status,
            last_event_at=self._last_event_at,
            total_events_collected=self._total_events_collected,
            error_count=self._error_count,
            last_error=self._last_error,
        )

    async def start(self, emit_callback: Callable[[TelemetryEvent], Awaitable[None]]) -> None:
        """Start periodic health probe background task."""
        self._emit_callback = emit_callback
        self._is_running = True
        self._status = CollectorStatus.HEALTHY
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._task = asyncio.create_task(self._probe_loop())
        logger.info("HealthCheckCollector %s started targeting %s", self._name, self._health_url)

    async def stop(self) -> None:
        """Stop background probe task and close HTTP client."""
        self._is_running = False
        self._status = CollectorStatus.STOPPED
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._client:
            await self._client.aclose()
            self._client = None

    async def _probe_loop(self) -> None:
        """Background probing loop."""
        while self._is_running:
            try:
                await self.probe_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._status = CollectorStatus.DEGRADED
                self._error_count += 1
                self._last_error = f"Probe error: {exc}"
                logger.error("Unhandled error in health check loop: %s", exc, exc_info=True)

            try:
                await asyncio.sleep(self._probe_interval)
            except asyncio.CancelledError:
                break

    async def probe_once(self) -> Optional[TelemetryEvent]:
        """Perform a single HTTP health probe, categorize failures, and emit TelemetryEvent."""
        if not self._client or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)

        now = datetime.now(timezone.utc)
        start_time = time.perf_counter()

        failure_type: Optional[str] = None
        status_code: Optional[int] = None
        error_message: Optional[str] = None
        exception_type: Optional[str] = None
        latency_ms: float = 0.0
        success: bool = False

        try:
            response = await self._client.get(self._health_url)
            latency_ms = (time.perf_counter() - start_time) * 1000
            status_code = response.status_code

            if 200 <= status_code < 400:
                success = True
            else:
                success = False
                failure_type = "http_status_failure"
                error_message = f"Health endpoint returned HTTP {status_code}"
                exception_type = "HttpStatusError"
        except httpx.ConnectError as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            success = False
            failure_type = "connection_refused"
            error_message = f"Connection refused to {self._health_url}: {exc}"
            exception_type = "ConnectError"
        except httpx.TimeoutException as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            success = False
            failure_type = "timeout"
            error_message = f"Health check timed out after {self._timeout}s: {exc}"
            exception_type = "TimeoutException"
        except httpx.RequestError as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            success = False
            failure_type = "network_error"
            error_message = f"Request error probing {self._health_url}: {exc}"
            exception_type = type(exc).__name__
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            success = False
            failure_type = "unknown_error"
            error_message = f"Unexpected error probing {self._health_url}: {exc}"
            exception_type = type(exc).__name__

        # Build telemetry event
        metadata: Dict[str, Any] = {
            "health_url": self._health_url,
            "latency_ms": round(latency_ms, 2),
        }

        if success:
            level = "INFO"
            event_type = "health_check_passed"
            message = f"Health check passed for {self._service} (HTTP {status_code}) in {latency_ms:.1f}ms"
            self._status = CollectorStatus.HEALTHY
        else:
            level = "ERROR"
            event_type = "health_check_failed"
            message = error_message or "Health check failed"
            metadata["failure_type"] = failure_type
            if status_code is not None:
                metadata["status_code"] = status_code
            self._status = CollectorStatus.DEGRADED
            self._error_count += 1
            self._last_error = message

        event = TelemetryEvent(
            event_id=str(uuid.uuid4()),
            project_id=self._project_id,
            service=self._service,
            environment=self._environment,
            signal_type=SignalType.HEALTH,
            source=self._name,
            timestamp=now,
            ingested_at=now,
            level=level,
            event_type=event_type,
            message=message,
            endpoint="/health",
            status_code=status_code,
            exception_type=exception_type,
            metadata=metadata,
        )

        if self._emit_callback:
            await self._emit_callback(event)
            self._total_events_collected += 1
            self._last_event_at = now

        return event
