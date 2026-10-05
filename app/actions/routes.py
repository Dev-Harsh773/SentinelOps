"""FastAPI HTTP routes for SentinelOps Safe Action Framework."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.actions.dependencies import get_action_service
from app.actions.models import (
    ActionAuditRecord,
    ApprovalStatus,
    ExecutionStatus,
    SafeAction,
)
from app.actions.schemas import (
    ActionApproveRequest,
    ActionAuditResponse,
    ActionProposeRequest,
    ActionRejectRequest,
    SafeActionResponse,
)
from app.actions.service import (
    ActionExecutionError,
    ActionNotFoundError,
    ActionService,
    DuplicateActiveActionError,
    InvalidActionStateTransitionError,
)

logger = logging.getLogger("sentinelops.actions.routes")

router = APIRouter(prefix="/actions", tags=["Safe Actions"])


def _action_to_response(action: SafeAction) -> SafeActionResponse:
    """Helper converting domain SafeAction to API schema."""
    return SafeActionResponse(
        action_id=action.action_id,
        project_id=action.project_id,
        incident_id=action.incident_id,
        action_type=action.action_type,
        target_type=action.target_type,
        target_id=action.target_id,
        parameters=action.parameters,
        fingerprint=action.fingerprint,
        requested_by_claim=action.requested_by_claim,
        risk_level=action.risk_level,
        policy_status=action.policy_status,
        policy_denial_reason=action.policy_denial_reason,
        approval_status=action.approval_status,
        execution_status=action.execution_status,
        created_at=action.created_at,
        updated_at=action.updated_at,
        approved_by_claim=action.approved_by_claim,
        approved_at=action.approved_at,
        approved_fingerprint=action.approved_fingerprint,
        rejection_reason=action.rejection_reason,
        executed_at=action.executed_at,
        completed_at=action.completed_at,
        execution_result=action.execution_result,
        failure_reason=action.failure_reason,
    )


def _audit_to_response(record: ActionAuditRecord) -> ActionAuditResponse:
    """Helper converting domain ActionAuditRecord to API schema."""
    return ActionAuditResponse(
        audit_id=record.audit_id,
        action_id=record.action_id,
        event_type=record.event_type,
        actor_claim=record.actor_claim,
        previous_state=record.previous_state,
        new_state=record.new_state,
        message=record.message,
        payload=record.payload,
        created_at=record.created_at,
    )


@router.post(
    "/propose",
    response_model=SafeActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Propose a new safe operational action",
)
def propose_action(
    payload: ActionProposeRequest,
    service: ActionService = Depends(get_action_service),
) -> SafeActionResponse:
    """Propose an action and evaluate Policy Check #1.

    Allowed actions transition to PENDING approval; policy-denied actions
    transition immediately to terminal CANCELLED / ABORTED state.
    """
    try:
        action = service.propose_action(
            project_id=payload.project_id,
            action_type=payload.action_type,
            target_type=payload.target_type,
            target_id=payload.target_id,
            parameters=payload.parameters,
            operator_claim=payload.operator_claim,
            incident_id=payload.incident_id,
        )
        return _action_to_response(action)
    except DuplicateActiveActionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "",
    response_model=List[SafeActionResponse],
    status_code=status.HTTP_200_OK,
    summary="List safe actions matching filters",
)
def list_actions(
    project_id: Optional[str] = Query(default=None, description="Filter by project_id"),
    incident_id: Optional[str] = Query(default=None, description="Filter by incident_id"),
    approval_status: Optional[ApprovalStatus] = Query(default=None, description="Filter by approval status"),
    execution_status: Optional[ExecutionStatus] = Query(default=None, description="Filter by execution status"),
    limit: int = Query(default=50, ge=1, le=200, description="Max actions to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    service: ActionService = Depends(get_action_service),
) -> List[SafeActionResponse]:
    """Retrieve filtered safe action records ordered newest first."""
    actions = service.list_actions(
        project_id=project_id,
        incident_id=incident_id,
        approval_status=approval_status,
        execution_status=execution_status,
        limit=limit,
        offset=offset,
    )
    return [_action_to_response(a) for a in actions]


@router.get(
    "/{action_id}",
    response_model=SafeActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get safe action by ID",
)
def get_action(
    action_id: str,
    service: ActionService = Depends(get_action_service),
) -> SafeActionResponse:
    """Retrieve details for a single safe action."""
    try:
        action = service.get_action(action_id)
        return _action_to_response(action)
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{action_id}/approve",
    response_model=SafeActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a pending safe action",
)
def approve_action(
    action_id: str,
    payload: ActionApproveRequest,
    service: ActionService = Depends(get_action_service),
) -> SafeActionResponse:
    """Submit explicit human approval for a pending safe action.

    Idempotent if already approved by the same operator claim with identical fingerprint.
    """
    try:
        action = service.approve_action(
            action_id=action_id,
            operator_claim=payload.operator_claim,
            comment=payload.comment,
        )
        return _action_to_response(action)
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidActionStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/{action_id}/reject",
    response_model=SafeActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject a pending safe action",
)
def reject_action(
    action_id: str,
    payload: ActionRejectRequest,
    service: ActionService = Depends(get_action_service),
) -> SafeActionResponse:
    """Submit explicit human rejection for a pending safe action.

    Idempotent if already rejected.
    """
    try:
        action = service.reject_action(
            action_id=action_id,
            operator_claim=payload.operator_claim,
            reason=payload.reason,
        )
        return _action_to_response(action)
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidActionStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/{action_id}/execute",
    response_model=SafeActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute an approved safe action",
)
async def execute_action(
    action_id: str,
    service: ActionService = Depends(get_action_service),
) -> SafeActionResponse:
    """Trigger execution of an approved safe action.

    Enforces Policy Check #2, authoritative DB execution claim, and executor execution.
    """
    try:
        action = await service.execute_action(action_id)
        return _action_to_response(action)
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ActionExecutionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc.message))


@router.get(
    "/{action_id}/audit",
    response_model=List[ActionAuditResponse],
    status_code=status.HTTP_200_OK,
    summary="Get audit trail for a safe action",
)
def get_action_audit(
    action_id: str,
    service: ActionService = Depends(get_action_service),
) -> List[ActionAuditResponse]:
    """Retrieve full append-only audit records for an action."""
    try:
        records = service.list_audits(action_id)
        return [_audit_to_response(r) for r in records]
    except ActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
