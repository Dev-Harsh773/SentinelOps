"""Desktop application configuration management.

Persists settings exclusively at %APPDATA%/SentinelOps/desktop_config.json,
with environment variable overrides (SENTINELOPS_API_URL, SENTINELOPS_POLL_INTERVAL)
for development and testing.
"""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Optional


def get_default_config_path() -> Path:
    """Return the authoritative persistent configuration path in APPDATA."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base_dir = Path(appdata)
    else:
        base_dir = Path.home() / ".config"
    return base_dir / "SentinelOps" / "desktop_config.json"


@dataclass
class DesktopConfig:
    """Configuration options for SentinelOps Windows Control Center."""

    backend_url: str = "http://127.0.0.1:8000"
    health_poll_interval_seconds: int = 10
    feed_poll_interval_seconds: int = 5
    incidents_poll_interval_seconds: int = 10
    connectors_poll_interval_seconds: int = 15
    request_timeout_seconds: float = 5.0
    reindex_timeout_seconds: float = 30.0
    window_width: int = 1280
    window_height: int = 850

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "DesktopConfig":
        """Load configuration from disk, applying environment variable overrides."""
        path = config_path or get_default_config_path()
        data = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        config = cls(
            backend_url=data.get("backend_url", "http://127.0.0.1:8000"),
            health_poll_interval_seconds=int(data.get("health_poll_interval_seconds", 10)),
            feed_poll_interval_seconds=int(data.get("feed_poll_interval_seconds", 5)),
            incidents_poll_interval_seconds=int(data.get("incidents_poll_interval_seconds", 10)),
            connectors_poll_interval_seconds=int(data.get("connectors_poll_interval_seconds", 15)),
            request_timeout_seconds=float(data.get("request_timeout_seconds", 5.0)),
            reindex_timeout_seconds=float(data.get("reindex_timeout_seconds", 30.0)),
            window_width=int(data.get("window_width", 1280)),
            window_height=int(data.get("window_height", 850)),
        )

        # Environment variable overrides
        env_url = os.environ.get("SENTINELOPS_API_URL")
        if env_url:
            config.backend_url = env_url.strip().rstrip("/")

        env_poll = os.environ.get("SENTINELOPS_POLL_INTERVAL")
        if env_poll:
            try:
                poll_val = int(env_poll)
                config.health_poll_interval_seconds = poll_val
                config.feed_poll_interval_seconds = max(2, poll_val // 2)
                config.incidents_poll_interval_seconds = poll_val
                config.connectors_poll_interval_seconds = poll_val
            except ValueError:
                pass

        return config

    def save(self, config_path: Optional[Path] = None) -> None:
        """Persist configuration to disk."""
        path = config_path or get_default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
