"""Centralized configuration for the demo application."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DemoAppConfig:
    """Demo application settings."""

    app_name: str
    host: str
    port: int
    log_level: str
    log_file_path: str

    @classmethod
    def from_env(cls) -> "DemoAppConfig":
        return cls(
            app_name=os.getenv("DEMO_APP_NAME", "demo-app"),
            host=os.getenv("DEMO_APP_HOST", "127.0.0.1"),
            port=int(os.getenv("DEMO_APP_PORT", "8001")),
            log_level=os.getenv("DEMO_APP_LOG_LEVEL", "INFO").upper(),
            log_file_path=os.getenv("DEMO_APP_LOG_PATH", "runtime/demo_app.jsonl"),
        )


demo_config = DemoAppConfig.from_env()
