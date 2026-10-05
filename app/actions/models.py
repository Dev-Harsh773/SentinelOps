"""Domain models, enums, and fingerprinting for SentinelOps Safe Action Framework."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional


# =====================================================================
# Domain Enums
# =====================================================================


class ActionType(str, Enum):
    """Explicitly allowlisted safe action types (deny-by-default)."""

    TEST_CONNECTOR = "test_connector"
    RETRY_NOTIFICATION = "retry_notification"


class TargetType(str, Enum):
    """Target entity category targeted by the safe action."""

    CONNECTOR = "connector"
    NOTIFICATION = "notification"


class RiskLevel(str, Enum):
    """Risk classification assigned to an action."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyStatus(str, Enum):
    """Outcome of policy engine evaluation."""

    ALLOWED = "allowed"
    DENIED = "denied"


class ApprovalStatus(str, Enum):
    """Human governance state of the action.

    NOTE: Approval is mandatory for every executable action in Stage 18.
    There is no NOT_REQUIRED bypass.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ExecutionStatus(str, Enum):
    """Runtime execution lifecycle state."""

    NOT_STARTED = "not_started"
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"


# =====================================================================
# Fingerprinting
# =====================================================================


def compute_action_fingerprint(
    action_type: ActionType,
    target_type: TargetType,
    target_id: str,
    project_id: str,
    incident_id: Optional[str],
    risk_level: RiskLevel,
    parameters: Dict[str, Any],
) -> str:
    """Computes a deterministic SHA-256 fingerprint of the immutable execution snapshot."""
    canonical_payload = {
        "action_type": action_type.value if isinstance(action_type, ActionType) else str(action_type),
        "target_type": target_type.value if isinstance(target_type, TargetType) else str(target_type),
        "target_id": str(target_id),
        "project_id": str(project_id),
        "incident_id": str(incident_id) if incident_id else None,
        "risk_level": risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level),
        "parameters": parameters,
    }
    encoded = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# =====================================================================
# Domain Entities
# =====================================================================


@dataclass
class SafeAction:
    """First-class operational action entity.

    All execution parameters, targets, and risk levels are immutable once proposed.
    """

    action_id: str
    project_id: str
    incident_id: Optional[str]
    action_type: ActionType
    target_type: TargetType
    target_id: str
    parameters: Dict[str, Any]
    fingerprint: str
    requested_by_claim: str
    risk_level: RiskLevel
    policy_status: PolicyStatus
    policy_denial_reason: Optional[str]
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


@dataclass
class ActionAuditRecord:
    """Immutable, append-only audit trail entry capturing lifecycle transitions."""

    audit_id: str
    action_id: str
    event_type: str
    actor_claim: str
    previous_state: Dict[str, Any]
    new_state: Dict[str, Any]
    message: str
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ActionResult:
    """Outcome payload returned by an action executor."""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
