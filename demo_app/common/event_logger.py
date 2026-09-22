"""Structured JSONL event logger for the demo application.

Appends structured JSON events to a local JSONL file for machine-readable
runtime evidence collection in SentinelOps, without altering console logging.
"""

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, Optional
from demo_app.common.config import demo_config


class JsonlEventLogger:
    """Writes uniform JSON-lines events to a configured file."""

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path = log_path or demo_config.log_file_path

    @property
    def log_path(self) -> str:
        return self._log_path

    def emit_event(
        self,
        *,
        level: str,
        service: str = "demo-app",
        request_id: Optional[str] = None,
        method: Optional[str] = None,
        endpoint: Optional[str] = None,
        event: str,
        message: str,
        status_code: Optional[int] = None,
        exception_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Emit a structured event conforming to the SentinelOps Stage 3 event schema."""
        event_time = timestamp or datetime.now(timezone.utc)
        iso_timestamp = event_time.isoformat()

        record: Dict[str, Any] = {
            "timestamp": iso_timestamp,
            "level": level.upper(),
            "service": service,
            "request_id": request_id,
            "method": method,
            "endpoint": endpoint,
            "event": event,
            "message": message,
            "status_code": status_code,
            "exception_type": exception_type,
            "metadata": metadata or {},
        }

        # Ensure directory exists before appending
        os.makedirs(os.path.dirname(os.path.abspath(self._log_path)), exist_ok=True)

        line = json.dumps(record, separators=(",", ":"))
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        return record


# Shared event logger instance
event_logger = JsonlEventLogger()
