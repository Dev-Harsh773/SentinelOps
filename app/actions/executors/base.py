"""Abstract base class contract for safe action executors."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple

from app.actions.models import ActionResult, ActionType, SafeAction


class BaseActionExecutor(ABC):
    """Abstract interface defining the execution protocol for allowlisted safe actions."""

    @property
    @abstractmethod
    def action_type(self) -> ActionType:
        """The specific action type handled by this executor."""
        pass

    @abstractmethod
    def validate_parameters(self, parameters: Dict[str, Any]) -> Tuple[bool, str]:
        """Validates parameter structure and bounds. Returns (is_valid, error_message)."""
        pass

    @abstractmethod
    async def dry_run(self, action: SafeAction) -> Dict[str, Any]:
        """Performs a non-mutating preview/simulation of the action."""
        pass

    @abstractmethod
    async def execute(self, action: SafeAction) -> ActionResult:
        """Executes the action and returns structured result payload."""
        pass
