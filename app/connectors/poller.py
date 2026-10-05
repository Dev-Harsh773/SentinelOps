"""Background polling runtime for HTTP poller connectors."""

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, Optional

import httpx

from app.connectors.models import (
    Connector,
    ConnectorHealth,
    ConnectorStatus,
    ConnectorType,
    OperationalStatus,
    TargetStatus,
)
from app.connectors.normalizer import normalize_poller_result
from app.connectors.store import SqliteConnectorStore
from app.watcher.service import WatcherService

logger = logging.getLogger("sentinelops.connectors.poller")


class ConnectorPollerRuntime:
    """Manages active polling tasks for HTTP poller connectors."""

    def __init__(
        self,
        store: SqliteConnectorStore,
        watcher_service: WatcherService,
    ) -> None:
        self._store = store
        self._watcher_service = watcher_service
        self._tasks: Dict[str, asyncio.Task] = {}
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        """Discover active HTTP poller connectors and launch background workers."""
        if self._is_running:
            return
        self._is_running = True
        connectors = self._store.list_connectors()
        for c in connectors:
            if c.connector_type == ConnectorType.HTTP_POLLER and c.status == ConnectorStatus.ACTIVE:
                await self.start_task(c)
        logger.info("ConnectorPollerRuntime started with %d active tasks", len(self._tasks))

    async def stop(self) -> None:
        """Cancel and wait for all active polling tasks."""
        self._is_running = False
        task_ids = list(self._tasks.keys())
        for cid in task_ids:
            await self.stop_task(cid)

        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            self._tasks.clear()
        logger.info("ConnectorPollerRuntime stopped cleanly")

    async def start_task(self, connector: Connector) -> None:
        """Start or restart a background polling task for a connector."""
        await self.stop_task(connector.connector_id)
        if not self._is_running:
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._poll_loop(connector.connector_id))
        self._tasks[connector.connector_id] = task

    async def stop_task(self, connector_id: str) -> None:
        """Cancel an active background polling task."""
        task = self._tasks.pop(connector_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Error awaiting cancelled task for %s: %s", connector_id, exc)

    async def _poll_loop(self, connector_id: str) -> None:
        """Execution loop for an individual HTTP poller connector."""
        while self._is_running:
            connector = self._store.get_connector(connector_id)
            if not connector or connector.status != ConnectorStatus.ACTIVE:
                break

            interval = connector.config.poll_interval_seconds
            try:
                poll_result = await self.execute_single_poll(connector)
                # If an operational error occurred, apply exponential backoff
                if poll_result.get("operational_error"):
                    err_count = poll_result.get("consecutive_operational_errors", 1)
                    backoff = min(300, 5 * (2 ** max(0, err_count - 1)))
                    interval = max(interval, backoff)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Unhandled top-level exception in poll loop for %s: %s", connector_id, exc)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def execute_single_poll(self, connector: Connector) -> Dict[str, Any]:
        """Execute one HTTP probe, classifying Target Health Failures vs. Operational Errors."""
        now = datetime.now(timezone.utc)
        url = connector.config.url
        health = self._store.get_health(connector.connector_id) or ConnectorHealth(
            connector_id=connector.connector_id
        )
        health.last_poll_at = now

        start_time = time.perf_counter()
        try:
            # Step 1: SSRF Validation
            from app.common.security import SSRFGuard, SSRFValidationError
            from app.connectors.redaction import scrub_string

            try:
                SSRFGuard.validate_url(url)
            except SSRFValidationError as ssrf_exc:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                health.operational_status = OperationalStatus.ERRORED
                health.consecutive_operational_errors += 1
                health.last_operational_error = f"SSRF violation: {ssrf_exc}"
                self._store.update_health(health)
                return {
                    "status": "operational_error",
                    "error": str(ssrf_exc),
                    "latency_ms": latency_ms,
                }

            # Step 2: Execute probe
            async with httpx.AsyncClient(timeout=connector.config.timeout_seconds, follow_redirects=False) as client:
                response = await client.request(
                    method=connector.config.method,
                    url=url,
                    headers=connector.config.headers,
                )
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                is_expected = response.status_code in connector.config.expected_status_codes
                if not is_expected:
                    # Target Failure: remote returned unexpected status code
                    health.target_status = TargetStatus.UNHEALTHY
                    health.last_target_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    if connector.config.emit_health_telemetry:
                        event = normalize_poller_result(
                            connector=connector,
                            status_code=response.status_code,
                            response_text=response.text,
                            latency_ms=latency_ms,
                            is_error=True,
                            error_message=f"Target health probe failed with status {response.status_code}",
                        )
                        await self._watcher_service.ingest_event(event)

                    self._store.update_health(health)
                    return {
                        "status": "target_failure",
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                    }

                # Success: target responded as expected
                old_op = health.operational_status
                health.operational_status = OperationalStatus.HEALTHY
                health.target_status = TargetStatus.HEALTHY
                health.consecutive_operational_errors = 0
                health.last_success_at = now
                health.last_operational_error = None
                health.last_target_error = None

                if old_op in (OperationalStatus.DEGRADED, OperationalStatus.ERRORED):
                    self._notify_operational_transition(
                        connector=connector,
                        old_status=old_op,
                        new_status=OperationalStatus.HEALTHY,
                        transition_time=now,
                    )

                if connector.config.emit_health_telemetry:
                    event = normalize_poller_result(
                        connector=connector,
                        status_code=response.status_code,
                        response_text=response.text,
                        latency_ms=latency_ms,
                        is_error=False,
                    )
                    await self._watcher_service.ingest_event(event)

                self._store.update_health(health)
                return {
                    "status": "success",
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                }

        except (httpx.RequestError, httpx.TimeoutException) as exc:
            # Target Failure: connection refused, timeout, DNS resolution error
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            health.target_status = TargetStatus.UNHEALTHY
            health.last_target_error = str(exc)

            if connector.config.emit_health_telemetry:
                event = normalize_poller_result(
                    connector=connector,
                    status_code=None,
                    response_text=None,
                    latency_ms=latency_ms,
                    is_error=True,
                    error_message=f"Target connection failed: {exc}",
                )
                await self._watcher_service.ingest_event(event)

            self._store.update_health(health)
            return {
                "status": "target_failure",
                "error": str(exc),
                "latency_ms": latency_ms,
            }

        except Exception as exc:
            # Operational Connector Error: internal software defect, client crash, SQLite failure
            old_op = health.operational_status
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            health.consecutive_operational_errors += 1
            health.operational_status = OperationalStatus.ERRORED
            health.last_operational_error = str(exc)

            if old_op == OperationalStatus.HEALTHY:
                self._notify_operational_transition(
                    connector=connector,
                    old_status=old_op,
                    new_status=OperationalStatus.ERRORED,
                    transition_time=now,
                    error_message=str(exc),
                )

            # Notice: Target status is NOT falsely declared unhealthy, and NO fake target telemetry is emitted!
            self._store.update_health(health)
            return {
                "status": "operational_error",
                "operational_error": True,
                "error": str(exc),
                "consecutive_operational_errors": health.consecutive_operational_errors,
            }

    def _notify_operational_transition(
        self,
        connector: Connector,
        old_status: OperationalStatus,
        new_status: OperationalStatus,
        transition_time: datetime,
        error_message: Optional[str] = None,
    ) -> None:
        """Dispatch operational health transition notification."""
        try:
            from app.notifications.dependencies import get_notification_service

            service = get_notification_service()
            service.on_connector_operational_transition(
                connector_id=connector.connector_id,
                project_id=connector.project_id,
                old_status=old_status,
                new_status=new_status,
                transition_time=transition_time,
                error_message=error_message,
            )
        except Exception as exc:
            logger.error(
                "Failed to dispatch connector operational notification for %s: %s",
                connector.connector_id,
                exc,
                exc_info=True,
            )
