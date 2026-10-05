"""Deny-by-default policy engine governing Safe Action proposal and execution eligibility."""

from dataclasses import dataclass
import logging
from typing import Any, Dict, Optional

from app.actions.models import (
    ActionType,
    PolicyStatus,
    RiskLevel,
    SafeAction,
    TargetType,
)
from app.actions.store import SqliteActionStore
from app.connectors.store import SqliteConnectorStore
from app.incidents.models import IncidentStatus
from app.incidents.service import IncidentService
from app.notifications.store import SqliteNotificationStore

logger = logging.getLogger("sentinelops.actions.policy")


@dataclass
class PolicyEvaluationResult:
    """Detailed result of a policy evaluation."""

    status: PolicyStatus
    reason: Optional[str] = None
    risk_level: RiskLevel = RiskLevel.LOW

    @property
    def is_allowed(self) -> bool:
        return self.status == PolicyStatus.ALLOWED


class ActionPolicyEngine:
    """Strict deny-by-default policy engine gating safe actions at proposal and re-validation."""

    def __init__(
        self,
        action_store: SqliteActionStore,
        connector_store: SqliteConnectorStore,
        notification_store: SqliteNotificationStore,
        incident_service: IncidentService,
    ) -> None:
        self._action_store = action_store
        self._connector_store = connector_store
        self._notification_store = notification_store
        self._incident_service = incident_service

    def evaluate_proposal(
        self,
        action_type: ActionType,
        target_type: TargetType,
        target_id: str,
        project_id: str,
        parameters: Dict[str, Any],
        incident_id: Optional[str] = None,
    ) -> PolicyEvaluationResult:
        """Evaluates policy rules during the initial proposal phase."""
        # 1. Allowlist check
        if action_type not in (ActionType.TEST_CONNECTOR, ActionType.RETRY_NOTIFICATION):
            return PolicyEvaluationResult(
                status=PolicyStatus.DENIED,
                reason=f"Action type '{action_type}' is not in the safe action allowlist.",
                risk_level=RiskLevel.HIGH,
            )

        # 2. Target type compatibility check
        if action_type == ActionType.TEST_CONNECTOR and target_type != TargetType.CONNECTOR:
            return PolicyEvaluationResult(
                status=PolicyStatus.DENIED,
                reason=f"Action '{action_type.value}' requires target_type '{TargetType.CONNECTOR.value}', got '{target_type.value}'.",
                risk_level=RiskLevel.HIGH,
            )
        if action_type == ActionType.RETRY_NOTIFICATION and target_type != TargetType.NOTIFICATION:
            return PolicyEvaluationResult(
                status=PolicyStatus.DENIED,
                reason=f"Action '{action_type.value}' requires target_type '{TargetType.NOTIFICATION.value}', got '{target_type.value}'.",
                risk_level=RiskLevel.HIGH,
            )

        # 3. Parameter bounds check (Stage 18 parameters must be strictly empty)
        if parameters:
            return PolicyEvaluationResult(
                status=PolicyStatus.DENIED,
                reason=f"Stage 18 action '{action_type.value}' accepts no parameters; parameters must be empty.",
                risk_level=RiskLevel.HIGH,
            )

        # 4. Target existence and project boundary check
        if target_type == TargetType.CONNECTOR:
            connector = self._connector_store.get_connector(target_id)
            if not connector:
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Connector target '{target_id}' does not exist.",
                    risk_level=RiskLevel.MEDIUM,
                )
            if connector.project_id != project_id:
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Connector target '{target_id}' belongs to project '{connector.project_id}', not '{project_id}'.",
                    risk_level=RiskLevel.HIGH,
                )

        elif target_type == TargetType.NOTIFICATION:
            try:
                notif = self._notification_store.get_notification(target_id)
            except Exception:
                notif = None
            if not notif:
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Notification target '{target_id}' does not exist.",
                    risk_level=RiskLevel.MEDIUM,
                )
            if notif.project_id != project_id:
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Notification target '{target_id}' belongs to project '{notif.project_id}', not '{project_id}'.",
                    risk_level=RiskLevel.HIGH,
                )

        # 5. Incident lifecycle check (if incident_id provided)
        if incident_id:
            incident = self._incident_service.get_incident(incident_id)
            if not incident:
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Associated incident '{incident_id}' does not exist.",
                    risk_level=RiskLevel.MEDIUM,
                )
            if incident.project_id != project_id:
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Incident '{incident_id}' belongs to project '{incident.project_id}', not '{project_id}'.",
                    risk_level=RiskLevel.HIGH,
                )
            if incident.status not in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Incident '{incident_id}' is in terminal status '{incident.status.value.upper()}'; actions cannot be proposed.",
                    risk_level=RiskLevel.MEDIUM,
                )

        # 6. Persistent active-action concurrency check
        if self._action_store.has_active_action_for_target(target_type, target_id):
            return PolicyEvaluationResult(
                status=PolicyStatus.DENIED,
                reason=f"An active action is already in flight for target '{target_type.value}:{target_id}'.",
                risk_level=RiskLevel.LOW,
            )

        # Passed all rules
        return PolicyEvaluationResult(
            status=PolicyStatus.ALLOWED,
            reason=None,
            risk_level=RiskLevel.LOW,
        )

    def evaluate_pre_execution(self, action: SafeAction) -> PolicyEvaluationResult:
        """Evaluates policy rules prior to execution (Policy Check #2)."""
        # Re-check incident status if incident_id bound
        if action.incident_id:
            incident = self._incident_service.get_incident(action.incident_id)
            if not incident:
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Incident '{action.incident_id}' no longer exists at execution time.",
                )
            if incident.status not in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                return PolicyEvaluationResult(
                    status=PolicyStatus.DENIED,
                    reason=f"Incident '{action.incident_id}' is now in terminal status '{incident.status.value.upper()}'; execution disallowed.",
                )

        return PolicyEvaluationResult(status=PolicyStatus.ALLOWED)
