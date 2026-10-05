"""Service orchestrating Safe Action lifecycle, policy checks, approvals, execution, and audits."""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.actions.executors.notification_retry import PrerequisiteConflictError
from app.actions.executors.registry import ActionExecutorRegistry
from app.actions.models import (
    ActionAuditRecord,
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    SafeAction,
    TargetType,
    compute_action_fingerprint,
)
from app.actions.policy import ActionPolicyEngine
from app.actions.store import (
    ActionNotFoundError,
    DuplicateActiveActionError,
    InvalidActionStateTransitionError,
    SqliteActionStore,
)

logger = logging.getLogger("sentinelops.actions.service")


class ActionExecutionError(Exception):
    """Raised when action execution fails, is disqualified, or encounters a conflict."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ActionService:
    """Core domain service for the Safe Action Framework."""

    def __init__(
        self,
        store: SqliteActionStore,
        policy_engine: ActionPolicyEngine,
        executor_registry: ActionExecutorRegistry,
        execution_timeout_seconds: float = 5.0,
    ) -> None:
        self._store = store
        self._policy_engine = policy_engine
        self._registry = executor_registry
        self._timeout_seconds = execution_timeout_seconds

    def propose_action(
        self,
        project_id: str,
        action_type: ActionType,
        target_type: TargetType,
        target_id: str,
        parameters: Dict[str, Any],
        operator_claim: str,
        incident_id: Optional[str] = None,
    ) -> SafeAction:
        """Proposes a new safe action, executing Policy Check #1."""
        now = datetime.now(timezone.utc)
        action_id = str(uuid.uuid4())

        # Evaluate Policy Check #1
        eval_result = self._policy_engine.evaluate_proposal(
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            project_id=project_id,
            parameters=parameters,
            incident_id=incident_id,
        )

        risk_level = eval_result.risk_level
        fingerprint = compute_action_fingerprint(
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            project_id=project_id,
            incident_id=incident_id,
            risk_level=risk_level,
            parameters=parameters,
        )

        audit_records: List[ActionAuditRecord] = []

        if not eval_result.is_allowed:
            # Policy-denied proposal is strictly terminal:
            # policy_status = DENIED, approval_status = CANCELLED, execution_status = ABORTED
            action = SafeAction(
                action_id=action_id,
                project_id=project_id,
                incident_id=incident_id,
                action_type=action_type,
                target_type=target_type,
                target_id=target_id,
                parameters=parameters,
                fingerprint=fingerprint,
                requested_by_claim=operator_claim,
                risk_level=risk_level,
                policy_status=PolicyStatus.DENIED,
                policy_denial_reason=eval_result.reason,
                approval_status=ApprovalStatus.CANCELLED,
                execution_status=ExecutionStatus.ABORTED,
                created_at=now,
                updated_at=now,
                failure_reason=eval_result.reason,
            )

            # Record POLICY_EVALUATED and POLICY_DENIED audit events
            audit_records.append(
                ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type="POLICY_EVALUATED",
                    actor_claim="system",
                    previous_state={},
                    new_state={"policy_status": PolicyStatus.DENIED.value},
                    message=f"Policy Check #1 evaluated: {eval_result.reason}",
                    payload={"status": "denied", "reason": eval_result.reason},
                    created_at=now,
                )
            )
            audit_records.append(
                ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type="POLICY_DENIED",
                    actor_claim="system",
                    previous_state={"approval_status": ApprovalStatus.PENDING.value},
                    new_state={
                        "policy_status": PolicyStatus.DENIED.value,
                        "approval_status": ApprovalStatus.CANCELLED.value,
                        "execution_status": ExecutionStatus.ABORTED.value,
                    },
                    message=f"Action proposal denied by policy: {eval_result.reason}",
                    payload={"reason": eval_result.reason},
                    created_at=now,
                )
            )
        else:
            # Policy allowed: moves to PENDING approval
            action = SafeAction(
                action_id=action_id,
                project_id=project_id,
                incident_id=incident_id,
                action_type=action_type,
                target_type=target_type,
                target_id=target_id,
                parameters=parameters,
                fingerprint=fingerprint,
                requested_by_claim=operator_claim,
                risk_level=risk_level,
                policy_status=PolicyStatus.ALLOWED,
                policy_denial_reason=None,
                approval_status=ApprovalStatus.PENDING,
                execution_status=ExecutionStatus.NOT_STARTED,
                created_at=now,
                updated_at=now,
            )

            audit_records.append(
                ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type="PROPOSED",
                    actor_claim=operator_claim,
                    previous_state={},
                    new_state={
                        "policy_status": PolicyStatus.ALLOWED.value,
                        "approval_status": ApprovalStatus.PENDING.value,
                        "execution_status": ExecutionStatus.NOT_STARTED.value,
                    },
                    message=f"Action proposed by {operator_claim}.",
                    payload={"fingerprint": fingerprint},
                    created_at=now,
                )
            )
            audit_records.append(
                ActionAuditRecord(
                    audit_id=str(uuid.uuid4()),
                    action_id=action_id,
                    event_type="POLICY_EVALUATED",
                    actor_claim="system",
                    previous_state={},
                    new_state={"policy_status": PolicyStatus.ALLOWED.value},
                    message="Policy Check #1 passed. Action eligible for human approval.",
                    payload={"status": "allowed"},
                    created_at=now,
                )
            )

        persisted_action = self._store.create_action(action, audit_records)
        return persisted_action

    def get_action(self, action_id: str) -> SafeAction:
        """Retrieves a single safe action by ID or raises ActionNotFoundError."""
        action = self._store.get_action(action_id)
        if not action:
            raise ActionNotFoundError(action_id)
        return action

    def list_actions(
        self,
        project_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        approval_status: Optional[ApprovalStatus] = None,
        execution_status: Optional[ExecutionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SafeAction]:
        """Lists safe actions matching optional filters."""
        return self._store.list_actions(
            project_id=project_id,
            incident_id=incident_id,
            approval_status=approval_status,
            execution_status=execution_status,
            limit=limit,
            offset=offset,
        )

    def approve_action(
        self,
        action_id: str,
        operator_claim: str,
        comment: Optional[str] = None,
    ) -> SafeAction:
        """Submits an explicit human approval for a pending safe action."""
        now = datetime.now(timezone.utc)
        action, _ = self._store.approve_action(
            action_id=action_id,
            operator_claim=operator_claim,
            comment=comment,
            now=now,
        )
        return action

    def reject_action(
        self,
        action_id: str,
        operator_claim: str,
        reason: str,
    ) -> SafeAction:
        """Submits an explicit human rejection for a pending safe action."""
        now = datetime.now(timezone.utc)
        action, _ = self._store.reject_action(
            action_id=action_id,
            operator_claim=operator_claim,
            reason=reason,
            now=now,
        )
        return action

    async def execute_action(self, action_id: str) -> SafeAction:
        """Executes an approved safe action with Policy Check #2 and atomic locking."""
        now = datetime.now(timezone.utc)
        action = self.get_action(action_id)

        # 1. State eligibility checks
        if action.approval_status != ApprovalStatus.APPROVED:
            raise ActionExecutionError(
                f"Action '{action_id}' is not approved (current status: '{action.approval_status.value}')."
            )
        if action.execution_status != ExecutionStatus.NOT_STARTED:
            raise ActionExecutionError(
                f"Action '{action_id}' is not in not_started state (current status: '{action.execution_status.value}')."
            )

        # 2. Policy Check #2: Re-check in-memory incident lifecycle prerequisite
        pre_check = self._policy_engine.evaluate_pre_execution(action)
        if not pre_check.is_allowed:
            abort_reason = pre_check.reason or "Policy re-evaluation failed before execution claim."
            self._store.abort_action(
                action_id=action_id,
                reason=abort_reason,
                event_type="POLICY_REVALIDATION_FAILED",
                actor_claim=action.approved_by_claim or "system",
                now=now,
            )
            raise ActionExecutionError(abort_reason)

        # 3. Authoritative Transactional Claim (validates fingerprint and DB targets)
        claimed, claimed_action, abort_reason = self._store.claim_action_for_execution(
            action_id=action_id,
            expected_fingerprint=action.approved_fingerprint or action.fingerprint,
            now=now,
        )

        if not claimed or not claimed_action:
            if abort_reason:
                raise ActionExecutionError(abort_reason)
            raise ActionExecutionError(f"Action '{action_id}' could not be claimed for execution.")

        # 4. Lookup allowlisted executor
        executor = self._registry.get(claimed_action.action_type)

        # 5. Execute with strict timeout
        try:
            result = await asyncio.wait_for(
                executor.execute(claimed_action),
                timeout=self._timeout_seconds,
            )

            completion_time = datetime.now(timezone.utc)
            if result.success:
                return self._store.complete_execution(
                    action_id=action_id,
                    final_status=ExecutionStatus.SUCCEEDED,
                    result=result.data,
                    failure_reason=None,
                    event_type="EXECUTION_COMPLETED",
                    actor_claim=claimed_action.approved_by_claim or "system",
                    message="Safe action executed successfully.",
                    now=completion_time,
                )
            else:
                return self._store.complete_execution(
                    action_id=action_id,
                    final_status=ExecutionStatus.FAILED,
                    result=result.data,
                    failure_reason=result.error_message or "Executor reported execution failure.",
                    event_type="EXECUTION_FAILED",
                    actor_claim=claimed_action.approved_by_claim or "system",
                    message=f"Safe action execution failed: {result.error_message}",
                    now=completion_time,
                )

        except PrerequisiteConflictError as exc:
            # Immediate side-effect precondition failed atomically (e.g. notification no longer FAILED)
            completion_time = datetime.now(timezone.utc)
            logger.warning("Prerequisite conflict during execution of %s: %s", action_id, exc)
            self._store.complete_execution(
                action_id=action_id,
                final_status=ExecutionStatus.ABORTED,
                result={"current_state": exc.current_state},
                failure_reason=exc.message,
                event_type="PREREQUISITE_CONFLICT_ABORTED",
                actor_claim=claimed_action.approved_by_claim or "system",
                message=f"Prerequisite conflict encountered: {exc.message}",
                now=completion_time,
            )
            raise ActionExecutionError(exc.message)

        except asyncio.TimeoutError:
            completion_time = datetime.now(timezone.utc)
            timeout_msg = f"Action execution timed out after {self._timeout_seconds} seconds."
            logger.error("Action %s timed out", action_id)
            self._store.complete_execution(
                action_id=action_id,
                final_status=ExecutionStatus.TIMED_OUT,
                result=None,
                failure_reason=timeout_msg,
                event_type="EXECUTION_FAILED",
                actor_claim=claimed_action.approved_by_claim or "system",
                message=timeout_msg,
                now=completion_time,
            )
            raise ActionExecutionError(timeout_msg)

        except Exception as exc:
            completion_time = datetime.now(timezone.utc)
            err_msg = str(exc)
            logger.error("Unexpected error executing action %s: %s", action_id, exc)
            self._store.complete_execution(
                action_id=action_id,
                final_status=ExecutionStatus.FAILED,
                result=None,
                failure_reason=err_msg,
                event_type="EXECUTION_FAILED",
                actor_claim=claimed_action.approved_by_claim or "system",
                message=f"Unexpected execution error: {err_msg}",
                now=completion_time,
            )
            raise ActionExecutionError(err_msg)

    def list_audits(self, action_id: str) -> List[ActionAuditRecord]:
        """Lists complete chronological audit history for an action."""
        self.get_action(action_id)  # Validate existence
        return self._store.list_audit_records(action_id)

    def reconcile_interrupted_executions(self) -> List[SafeAction]:
        """Reconciles in-flight execution claims orphaned across process restart."""
        reconciled = self._store.reconcile_interrupted_executions_on_startup()
        if reconciled:
            logger.warning(
                "Startup reconciliation: marked %d orphaned action(s) as aborted: %s",
                len(reconciled),
                [a.action_id for a in reconciled],
            )
        return reconciled
