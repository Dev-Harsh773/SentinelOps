"""Continuous JSONL file tailing collector for Sentinel Watcher.

Monitors a configured structured JSONL log file, begins reading from EOF on startup
to avoid re-ingesting historical lines, handles log truncation/rotation safely,
and normalizes new lines into TelemetryEvent records.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Awaitable, Callable, Dict, Optional
import uuid

from app.watcher.collectors.base import TelemetryCollector
from app.watcher.models import CollectorHealth, CollectorStatus, CollectorType, SignalType, TelemetryEvent

logger = logging.getLogger("sentinelops.watcher.collectors.file")


class JsonlFileCollector(TelemetryCollector):
    """Active background observer tailing a structured JSONL log file."""

    def __init__(
        self,
        log_path: str,
        project_id: str,
        service: str,
        environment: str,
        poll_interval_seconds: float = 1.0,
        name: str = "jsonl_file_collector",
    ) -> None:
        self._log_path = log_path
        self._project_id = project_id
        self._service = service
        self._environment = environment
        self._poll_interval = poll_interval_seconds
        self._name = name

        self._offset: int = 0
        self._is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._emit_callback: Optional[Callable[[TelemetryEvent], Awaitable[None]]] = None

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
        return CollectorType.FILE

    @property
    def log_path(self) -> str:
        return self._log_path

    @property
    def offset(self) -> int:
        return self._offset

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
        """Start the tailing loop, seeking to EOF if file exists."""
        self._emit_callback = emit_callback
        self._is_running = True
        self._status = CollectorStatus.HEALTHY

        # Explicit startup behavior: seek to EOF if file exists to capture only new telemetry
        if os.path.exists(self._log_path):
            try:
                self._offset = os.path.getsize(self._log_path)
                logger.info(
                    "Collector %s initialized at EOF offset %d in %s",
                    self._name,
                    self._offset,
                    self._log_path,
                )
            except OSError as exc:
                self._offset = 0
                self._error_count += 1
                self._last_error = f"Error reading initial file size: {exc}"
                logger.warning("Error getting size of %s: %s", self._log_path, exc)
        else:
            self._offset = 0
            logger.info("Collector %s waiting for log file %s to be created", self._name, self._log_path)

        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop background tailing task."""
        self._is_running = False
        self._status = CollectorStatus.STOPPED
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self) -> None:
        """Continuous polling loop."""
        while self._is_running:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._status = CollectorStatus.DEGRADED
                self._error_count += 1
                self._last_error = f"Poll error: {exc}"
                logger.error("Unhandled error in file collector poll loop: %s", exc, exc_info=True)

            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def poll_once(self) -> int:
        """Read newly appended lines from log file, update offset, and emit events.

        Returns the number of events emitted during this poll cycle.
        """
        if not os.path.exists(self._log_path):
            return 0

        emitted_count = 0
        try:
            current_size = os.path.getsize(self._log_path)
            # Detect truncation or log rotation
            if current_size < self._offset:
                logger.warning(
                    "Log file %s truncated (size %d < offset %d), resetting offset to 0",
                    self._log_path,
                    current_size,
                    self._offset,
                )
                self._offset = 0

            if current_size == self._offset:
                return 0

            with open(self._log_path, "r", encoding="utf-8") as f:
                f.seek(self._offset)
                while self._is_running:
                    line = f.readline()
                    if not line:
                        break

                    self._offset = f.tell()
                    line_str = line.strip()
                    if not line_str:
                        continue

                    # Safe JSON parsing
                    try:
                        record = json.loads(line_str)
                    except json.JSONDecodeError as exc:
                        self._error_count += 1
                        self._last_error = f"Malformed JSON: {exc}"
                        logger.warning("Skipping malformed JSON line in %s: %s", self._log_path, exc)
                        continue

                    if not isinstance(record, dict):
                        continue

                    event = self._normalize_record(record)
                    if event and self._emit_callback:
                        await self._emit_callback(event)
                        self._total_events_collected += 1
                        self._last_event_at = event.ingested_at
                        emitted_count += 1

            self._status = CollectorStatus.HEALTHY
        except Exception as exc:
            self._status = CollectorStatus.DEGRADED
            self._error_count += 1
            self._last_error = str(exc)
            logger.error("Error reading log file %s: %s", self._log_path, exc)

        return emitted_count

    def _normalize_record(self, record: Dict[str, Any]) -> Optional[TelemetryEvent]:
        """Normalize raw JSON dictionary into TelemetryEvent domain model."""
        raw_ts = record.get("timestamp")
        parsed_dt: Optional[datetime] = None
        if raw_ts and isinstance(raw_ts, str):
            try:
                clean_ts = raw_ts.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_ts)
                parsed_dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                parsed_dt = datetime.now(timezone.utc)
        else:
            parsed_dt = datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        level = str(record.get("level", "INFO")).upper()
        event_type = str(record.get("event") or record.get("event_type") or "log_event")
        message = str(record.get("message") or "")
        service_name = str(record.get("service") or self._service)
        request_id = record.get("request_id")
        trace_id = record.get("trace_id")
        endpoint = record.get("endpoint")
        status_code = record.get("status_code")
        exception_type = record.get("exception_type")
        metadata = record.get("metadata") or {}

        return TelemetryEvent(
            event_id=str(uuid.uuid4()),
            project_id=self._project_id,
            service=service_name,
            environment=self._environment,
            signal_type=SignalType.LOG,
            source=self._name,
            timestamp=parsed_dt,
            ingested_at=now,
            level=level,
            event_type=event_type,
            message=message,
            request_id=request_id,
            trace_id=trace_id,
            endpoint=endpoint,
            status_code=status_code,
            exception_type=exception_type,
            metadata=metadata if isinstance(metadata, dict) else {"raw": metadata},
        )
