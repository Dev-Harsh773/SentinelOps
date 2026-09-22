"""Pytest fixtures for the demo application test suite."""

import pytest
from fastapi.testclient import TestClient

from demo_app.common.event_logger import event_logger
from demo_app.failure_modes.controller import get_failure_controller
from demo_app.main import app


@pytest.fixture(autouse=True)
def reset_failure_modes(tmp_path):
    """Ensure failure mode state and log paths are reset before and after every test."""
    controller = get_failure_controller()
    controller.reset()

    # Isolate event logging to temporary directory during demo_app tests
    original_log_path = event_logger._log_path
    event_logger._log_path = str(tmp_path / "test_demo_events.jsonl")

    yield

    controller.reset()
    event_logger._log_path = original_log_path


@pytest.fixture
def client():
    """Provide a TestClient instance targeting the demo application."""
    return TestClient(app)
