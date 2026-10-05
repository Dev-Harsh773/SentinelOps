"""Registry for registering and looking up safe action executors."""

from typing import Dict

from app.actions.executors.base import BaseActionExecutor
from app.actions.models import ActionType


class UnsupportedActionTypeError(Exception):
    """Raised when no executor is registered for an action type."""

    def __init__(self, action_type: str) -> None:
        super().__init__(f"No executor registered for action type '{action_type}'.")
        self.action_type = action_type


class ActionExecutorRegistry:
    """Manages the lifecycle and discovery of allowlisted safe action executors."""

    def __init__(self) -> None:
        self._executors: Dict[ActionType, BaseActionExecutor] = {}

    def register(self, executor: BaseActionExecutor) -> None:
        """Registers a safe action executor."""
        self._executors[executor.action_type] = executor

    def get(self, action_type: ActionType) -> BaseActionExecutor:
        """Retrieves the executor for an action type or raises UnsupportedActionTypeError."""
        executor = self._executors.get(action_type)
        if not executor:
            raise UnsupportedActionTypeError(action_type.value if hasattr(action_type, "value") else str(action_type))
        return executor
