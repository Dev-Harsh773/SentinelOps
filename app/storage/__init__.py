"""Data persistence and storage access module.

Exports storage adapters for SentinelOps local and persistent operational data.
"""

from app.watcher.storage import SqliteTelemetryStore

__all__ = ["SqliteTelemetryStore"]
