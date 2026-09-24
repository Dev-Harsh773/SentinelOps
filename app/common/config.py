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
    llm_provider: str
    llm_model: str
    openai_api_key: Optional[str]
    git_context_limit: int
    rca_max_revisions: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        # Read from environment with sensible local development defaults
        # so the application can run out-of-the-box without requiring a .env file.
        return cls(
            app_name=os.getenv("APP_NAME", "sentinelops"),
            app_env=os.getenv("APP_ENV", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8000")),
            demo_app_log_path=os.getenv("DEMO_APP_LOG_PATH", "runtime/demo_app.jsonl"),
            source_repository_path=os.getenv("SOURCE_REPOSITORY_PATH", "demo_app"),
            git_repository_path=os.getenv("GIT_REPOSITORY_PATH", "."),
            llm_provider=os.getenv("LLM_PROVIDER", "mock").lower(),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            git_context_limit=int(os.getenv("GIT_CONTEXT_LIMIT", "3")),
            rca_max_revisions=int(os.getenv("RCA_MAX_REVISIONS", "1")),
        )


# Instantiate a singleton configuration instance for consistent imports across the app
config = AppConfig.from_env()
