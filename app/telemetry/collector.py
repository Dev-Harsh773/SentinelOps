"""Generic runtime log collector for reading structured JSONL event records.

Reads configured JSONL log files, handles malformed lines gracefully, and returns
structured event dictionaries with validated timezone-aware timestamps.
Does not contain domain-specific filtering rules (e.g. failure selection).
"""

from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinelops.telemetry.collector")


class RuntimeLogCollector:
    """Reads and parses raw structured JSONL runtime logs."""

    def __init__(self, log_path: str) -> None:
        self._log_path = log_path

    @property
    def log_path(self) -> str:
        return self._log_path

    def collect_events_for_request(self, request_id: str) -> List[Dict[str, Any]]:
        """Read the JSONL file and return all valid events matching request_id.

        Safely skips malformed JSON lines and events with invalid timestamps.
        If the log file does not exist, returns an empty list without raising an exception.
        """
        if not os.path.exists(self._log_path):
            logger.warning("Runtime log file not found at path: %s", self._log_path)
            return []

        matching_events: List[Dict[str, Any]] = []

        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line_str = line.strip()
                    if not line_str:
                        continue

                    # Safe JSON parsing
                    try:
                        record = json.loads(line_str)
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "Skipping malformed JSON line %d in %s: %s",
                            line_num,
                            self._log_path,
                            exc,
                        )
                        continue

                    if not isinstance(record, dict):
                        continue

                    # Filter by request ID
                    if record.get("request_id") != request_id:
                        continue

                    # Validate and parse timestamp into timezone-aware UTC datetime
                    raw_ts = record.get("timestamp")
                    parsed_dt: Optional[datetime] = None
                    if raw_ts and isinstance(raw_ts, str):
                        try:
                            # Parse ISO format, handling 'Z' as UTC
                            clean_ts = raw_ts.replace("Z", "+00:00")
                            dt = datetime.fromisoformat(clean_ts)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            else:
                                dt = dt.astimezone(timezone.utc)
                            parsed_dt = dt
                        except (ValueError, TypeError) as exc:
                            logger.warning(
                                "Skipping event with invalid timestamp '%s' at line %d in %s: %s",
                                raw_ts,
                                line_num,
                                self._log_path,
                                exc,
                            )
                            continue
                    else:
                        logger.warning(
                            "Skipping event missing valid timestamp string at line %d in %s",
                            line_num,
                            self._log_path,
                        )
                        continue

                    # Attach parsed datetime to the event record
                    record["_parsed_datetime"] = parsed_dt
                    matching_events.append(record)

        except Exception as exc:
            logger.error("Error reading runtime log file %s: %s", self._log_path, exc, exc_info=True)
            return []

        return matching_events
