"""Centralized application configuration.

Uses standard library dataclasses and environment variables to avoid
external dependency overhead during early foundation stages while ensuring
settings are configurable across environments.
"""

from dataclasses import dataclass
import os
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class AppConfig:
    """Application configuration container."""

    app_name: str
    app_env: str
    log_level: str
    host: str
    port: int
    demo_app_log_path: str
    source_repository_path: str
    git_repository_path: str
    git_branch_repository_path: str
    git_base_branch: str
    llm_provider: str
    llm_model: str
    openai_api_key: Optional[str]
    git_context_limit: int
    rca_max_revisions: int
    watcher_enabled: bool
    watcher_log_path: str
    watcher_poll_interval_seconds: float
    watcher_buffer_capacity: int
    watcher_db_path: str
    watcher_db_retention_hours: int
    watcher_db_max_events: int
    watcher_health_check_interval_seconds: float
    watcher_health_check_url: str
    watcher_default_project_id: str
    watcher_default_service: str
    watcher_default_environment: str
    detection_enabled: bool
    correlation_enabled: bool
    correlation_pre_window_seconds: float
    correlation_post_window_seconds: float
    correlation_fallback_window_seconds: float
    correlation_max_evidence_per_incident: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        # Read from environment with sensible local development defaults
        # so the application can run out-of-the-box without requiring a .env file.
        git_repo_path = os.getenv("GIT_REPOSITORY_PATH", ".")
        git_branch_repo_path = os.getenv("GIT_BRANCH_REPOSITORY_PATH") or git_repo_path
        git_base_branch = os.getenv("GIT_BASE_BRANCH", "main")
        demo_log_path = os.getenv("DEMO_APP_LOG_PATH", "runtime/demo_app.jsonl")
        watcher_log_path = os.getenv("WATCHER_LOG_PATH") or demo_log_path

        return cls(
            app_name=os.getenv("APP_NAME", "sentinelops"),
            app_env=os.getenv("APP_ENV", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8000")),
            demo_app_log_path=demo_log_path,
            source_repository_path=os.getenv("SOURCE_REPOSITORY_PATH", "demo_app"),
            git_repository_path=git_repo_path,
            git_branch_repository_path=git_branch_repo_path,
            git_base_branch=git_base_branch,
            llm_provider=os.getenv("LLM_PROVIDER", "mock").lower(),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            git_context_limit=int(os.getenv("GIT_CONTEXT_LIMIT", "3")),
            rca_max_revisions=int(os.getenv("RCA_MAX_REVISIONS", "1")),
            watcher_enabled=os.getenv("WATCHER_ENABLED", "true").lower() in ("true", "1", "yes"),
            watcher_log_path=watcher_log_path,
            watcher_poll_interval_seconds=float(os.getenv("WATCHER_POLL_INTERVAL_SECONDS", "1.0")),
            watcher_buffer_capacity=int(os.getenv("WATCHER_BUFFER_CAPACITY", "1000")),
            watcher_db_path=os.getenv("WATCHER_DB_PATH", "runtime/sentinelops.db"),
            watcher_db_retention_hours=int(os.getenv("WATCHER_DB_RETENTION_HOURS", "24")),
            watcher_db_max_events=int(os.getenv("WATCHER_DB_MAX_EVENTS", "10000")),
            watcher_health_check_interval_seconds=float(os.getenv("WATCHER_HEALTH_CHECK_INTERVAL_SECONDS", "5.0")),
            watcher_health_check_url=os.getenv("WATCHER_HEALTH_CHECK_URL", "http://127.0.0.1:8001/health"),
            watcher_default_project_id=os.getenv("WATCHER_DEFAULT_PROJECT_ID", "sentinelops-demo"),
            watcher_default_service=os.getenv("WATCHER_DEFAULT_SERVICE", "demo-app"),
            watcher_default_environment=os.getenv("WATCHER_DEFAULT_ENVIRONMENT", "development"),
            detection_enabled=os.getenv("DETECTION_ENABLED", "true").lower() in ("true", "1", "yes"),
            correlation_enabled=os.getenv("CORRELATION_ENABLED", "true").lower() in ("true", "1", "yes"),
            correlation_pre_window_seconds=float(os.getenv("CORRELATION_PRE_WINDOW_SECONDS", "60.0")),
            correlation_post_window_seconds=float(os.getenv("CORRELATION_POST_WINDOW_SECONDS", "30.0")),
            correlation_fallback_window_seconds=float(os.getenv("CORRELATION_FALLBACK_WINDOW_SECONDS", "10.0")),
            correlation_max_evidence_per_incident=int(os.getenv("CORRELATION_MAX_EVIDENCE_PER_INCIDENT", "20")),
        )


# Instantiate a singleton configuration instance for consistent imports across the app
config = AppConfig.from_env()
