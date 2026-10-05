"""Pydantic schemas for the Safe Action Framework API."""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from app.actions.models import (
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    TargetType,
)


class ActionProposeRequest(BaseModel):
    """Payload for proposing a new safe action."""

    project_id: str = Field(min_length=1, max_length=100, description="Target project identifier")
    incident_id: Optional[str] = Field(default=None, max_length=100, description="Associated incident ID if any")
    action_type: ActionType = Field(description="Allowlisted safe action type")
    target_type: TargetType = Field(description="Target entity type")
    target_id: str = Field(min_length=1, max_length=100, description="Target entity identifier")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Action parameters (must be empty in Stage 18)")
    operator_claim: str = Field(min_length=1, max_length=100, description="Operator attribution claim")


class ActionApproveRequest(BaseModel):
    """Payload for explicitly approving a pending safe action."""

    operator_claim: str = Field(min_length=1, max_length=100, description="Operator attribution claim")
    comment: Optional[str] = Field(default=None, max_length=1000, description="Optional approval notes")


class ActionRejectRequest(BaseModel):
    """Payload for rejecting a pending safe action."""

    operator_claim: str = Field(min_length=1, max_length=100, description="Operator attribution claim")
    reason: str = Field(min_length=1, max_length=1000, description="Rejection rationale")


class SafeActionResponse(BaseModel):
    """API representation of a SafeAction entity."""

    action_id: str
    project_id: str
    incident_id: Optional[str] = None
    action_type: ActionType
    target_type: TargetType
    target_id: str
    parameters: Dict[str, Any]
    fingerprint: str
    requested_by_claim: str
    risk_level: RiskLevel
    policy_status: PolicyStatus
    policy_denial_reason: Optional[str] = None
    approval_status: ApprovalStatus
    execution_status: ExecutionStatus
    created_at: datetime
    updated_at: datetime
    approved_by_claim: Optional[str] = None
    approved_at: Optional[datetime] = None
    approved_fingerprint: Optional[str] = None
    rejection_reason: Optional[str] = None
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_result: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None


class ActionAuditResponse(BaseModel):
    """API representation of an ActionAuditRecord."""

    audit_id: str
    action_id: str
    event_type: str
    actor_claim: str
    previous_state: Dict[str, Any]
    new_state: Dict[str, Any]
    message: str
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime
