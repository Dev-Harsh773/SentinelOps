"""Executor for the RETRY_NOTIFICATION safe action."""

import logging
import time
from typing import Any, Dict, Optional, Tuple

from app.actions.executors.base import BaseActionExecutor
from app.actions.models import ActionResult, ActionType, SafeAction
from app.notifications.service import NotificationService

logger = logging.getLogger("sentinelops.actions.executors.notification_retry")


class PrerequisiteConflictError(Exception):
    """Raised when an execution-time prerequisite fails atomically (e.g. state drift)."""

    def __init__(self, message: str, current_state: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.current_state = current_state


class NotificationRetryExecutor(BaseActionExecutor):
    """Executes atomic requeue for a failed notification."""

    def __init__(self, notification_service: NotificationService) -> None:
        self._notification_service = notification_service

    @property
    def action_type(self) -> ActionType:
        return ActionType.RETRY_NOTIFICATION

    def validate_parameters(self, parameters: Dict[str, Any]) -> Tuple[bool, str]:
        if parameters:
            return False, "RETRY_NOTIFICATION accepts no parameters; parameters must be empty."
        return True, ""

    async def dry_run(self, action: SafeAction) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "target_id": action.target_id,
            "simulated": True,
            "message": f"Would atomically reset failed notification '{action.target_id}' to pending.",
        }

    async def execute(self, action: SafeAction) -> ActionResult:
        start_time = time.perf_counter()
        # Atomic conditional reset at notification store boundary
        success, notif_response, current_status = self._notification_service.atomic_retry_notification(
            action.target_id
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        if not success:
            if not notif_response:
                raise PrerequisiteConflictError(
                    f"Notification target '{action.target_id}' not found.",
                    current_state="missing",
                )
            status_val = current_status.value if current_status else "unknown"
            raise PrerequisiteConflictError(
                f"Notification is no longer in FAILED state (current: {status_val}).",
                current_state=status_val,
            )

        return ActionResult(
            success=True,
            data={
                "notification_id": notif_response.notification_id,
                "delivery_status": notif_response.delivery_status.value,
                "attempt_count": notif_response.attempt_count,
            },
            execution_time_ms=round(elapsed_ms, 2),
        )
