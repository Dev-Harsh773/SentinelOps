"""Failure mode controller for the demo application.

Maintains explicit, reversible runtime flags that trigger deterministic failure
scenarios for SentinelOps investigation.
"""

from typing import Dict


class FailureModeController:
    """Manages controllable failure modes for the demo application."""

    def __init__(self) -> None:
        self._order_processing_error: bool = False

    def enable_order_processing_error(self) -> None:
        """Enable the order processing error failure mode."""
        self._order_processing_error = True

    def disable_order_processing_error(self) -> None:
        """Disable the order processing error failure mode."""
        self._order_processing_error = False

    def is_order_processing_error_enabled(self) -> bool:
        """Check whether the order processing error is active."""
        return self._order_processing_error

    def get_status(self) -> Dict[str, bool]:
        """Return the current state of all controlled failure modes."""
        return {
            "order_processing_error": self._order_processing_error,
        }

    def reset(self) -> None:
        """Reset all failure modes to default (disabled). Reserved for test isolation."""
        self._order_processing_error = False


# Shared runtime singleton instance
failure_controller = FailureModeController()


def get_failure_controller() -> FailureModeController:
    """Provide the failure controller instance."""
    return failure_controller
