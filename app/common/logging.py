"""Consistent application logging setup.

Configures standard library logging with uniform formatting to prevent ad-hoc
print() statements across modules while keeping Stage 0 free from heavy external
logging frameworks.
"""

import logging
import sys
from app.common.config import config


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

    return logging.getLogger(config.app_name)


logger = setup_logging()
