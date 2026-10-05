"""Unit tests for Safe Action domain models, enums, and fingerprinting."""

import pytest

from app.actions.models import (
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    TargetType,
    compute_action_fingerprint,
)


def test_action_enums():
    """Verify that all required domain enums match expected values."""
    assert ActionType.TEST_CONNECTOR == "test_connector"
    assert ActionType.RETRY_NOTIFICATION == "retry_notification"

    assert TargetType.CONNECTOR == "connector"
    assert TargetType.NOTIFICATION == "notification"

    assert RiskLevel.LOW == "low"
    assert RiskLevel.MEDIUM == "medium"
    assert RiskLevel.HIGH == "high"
    assert RiskLevel.CRITICAL == "critical"

    assert PolicyStatus.ALLOWED == "allowed"
    assert PolicyStatus.DENIED == "denied"

    assert ApprovalStatus.PENDING == "pending"
    assert ApprovalStatus.APPROVED == "approved"
    assert ApprovalStatus.REJECTED == "rejected"
    assert ApprovalStatus.CANCELLED == "cancelled"
    # Ensure no NOT_REQUIRED bypass enum exists
    assert not hasattr(ApprovalStatus, "NOT_REQUIRED")

    assert ExecutionStatus.NOT_STARTED == "not_started"
    assert ExecutionStatus.PENDING == "pending"
    assert ExecutionStatus.EXECUTING == "executing"
    assert ExecutionStatus.SUCCEEDED == "succeeded"
    assert ExecutionStatus.FAILED == "failed"
    assert ExecutionStatus.TIMED_OUT == "timed_out"
    assert ExecutionStatus.ABORTED == "aborted"


def test_fingerprint_deterministic_and_immutable():
    """Verify deterministic SHA-256 fingerprinting."""
    fp1 = compute_action_fingerprint(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        project_id="proj-1",
        incident_id="inc-1",
        risk_level=RiskLevel.LOW,
        parameters={},
    )
    fp2 = compute_action_fingerprint(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        project_id="proj-1",
        incident_id="inc-1",
        risk_level=RiskLevel.LOW,
        parameters={},
    )
    assert fp1 == fp2
    assert len(fp1) == 64

    # Any change produces a distinct fingerprint
    fp_diff_target = compute_action_fingerprint(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-2",
        project_id="proj-1",
        incident_id="inc-1",
        risk_level=RiskLevel.LOW,
        parameters={},
    )
    assert fp1 != fp_diff_target

    fp_diff_incident = compute_action_fingerprint(
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-1",
        project_id="proj-1",
        incident_id=None,
        risk_level=RiskLevel.LOW,
        parameters={},
    )
    assert fp1 != fp_diff_incident
