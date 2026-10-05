"""Executor for the TEST_CONNECTOR safe action."""

import logging
import time
from typing import Any, Dict, Tuple

from app.actions.executors.base import BaseActionExecutor
from app.actions.models import ActionResult, ActionType, SafeAction
from app.connectors.service import ConnectorService

logger = logging.getLogger("sentinelops.actions.executors.connector_test")


class ConnectorTestExecutor(BaseActionExecutor):
    """Executes non-mutating diagnostic connectivity test against a registered connector."""

    def __init__(self, connector_service: ConnectorService) -> None:
        self._connector_service = connector_service

    @property
    def action_type(self) -> ActionType:
        return ActionType.TEST_CONNECTOR

    def validate_parameters(self, parameters: Dict[str, Any]) -> Tuple[bool, str]:
        if parameters:
            return False, "TEST_CONNECTOR accepts no parameters; parameters must be empty."
        return True, ""

    async def dry_run(self, action: SafeAction) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "target_id": action.target_id,
            "simulated": True,
            "message": f"Would perform connectivity test on connector '{action.target_id}'.",
        }

    async def execute(self, action: SafeAction) -> ActionResult:
        start_time = time.perf_counter()
        try:
            result_data = await self._connector_service.test_connector(action.target_id)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            status_str = result_data.get("status", "unknown")
            success = status_str in ("success", "active")

            return ActionResult(
                success=success,
                data=result_data,
                error_message=result_data.get("error"),
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error("Failed to execute connector test for %s: %s", action.target_id, exc)
            return ActionResult(
                success=False,
                data={"status": "error", "connector_id": action.target_id},
                error_message=str(exc),
                execution_time_ms=round(elapsed_ms, 2),
            )
