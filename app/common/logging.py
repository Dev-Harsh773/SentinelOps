"""Consistent application logging setup.

Configures standard library logging with uniform formatting to prevent ad-hoc
print() statements across modules while keeping Stage 0 free from heavy external
logging frameworks.
"""

import logging
import sys
import json
import re
from datetime import datetime, timezone
from app.common.config import config


class SafeJsonFormatter(logging.Formatter):
    """Production logs omit transport URLs and exception text containing secrets."""
    def format(self, record):
        message = record.getMessage()
        for secret in (config.operator_token, config.openai_api_key):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        message = re.sub(r"https?://[^\s\"'<>]+", "[REDACTED_URL]", message)
        message = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", message)
        message = re.sub(r"(?i)((?:secret|token|api[_-]?key|authorization)\s*[=:]\s*)\S+", r"\1[REDACTED]", message)
        result = {"timestamp": datetime.now(timezone.utc).isoformat(),
                  "level": record.levelname, "logger": record.name, "message": message}
        if record.exc_info:
            result["exception_type"] = record.exc_info[0].__name__
        return json.dumps(result, ensure_ascii=True)


def setup_logging() -> logging.Logger:
    """Initialize root logging configuration according to application settings."""
    log_format = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    numeric_level = getattr(logging, config.log_level, logging.INFO)

    # Configure the root handler explicitly for standard output
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    if config.production or config.log_json:
        for handler in logging.getLogger().handlers:
            handler.setFormatter(SafeJsonFormatter())

    return logging.getLogger(config.app_name)


logger = setup_logging()
