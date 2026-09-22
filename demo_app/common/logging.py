"""Structured logging setup for the demo application."""

import logging
import sys
from demo_app.common.config import demo_config


def setup_demo_logging() -> logging.Logger:
    """Initialize standard logging format for demo application."""
    log_format = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    numeric_level = getattr(logging, demo_config.log_level, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=False,
    )

    return logging.getLogger(demo_config.app_name)


demo_logger = setup_demo_logging()
