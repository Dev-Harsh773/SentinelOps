"""Unit tests for ConnectorTestExecutor and NotificationRetryExecutor."""

from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.actions.executors.connector_test import ConnectorTestExecutor
from app.actions.executors.notification_retry import (
    NotificationRetryExecutor,
    PrerequisiteConflictError,
)
from app.actions.models import (
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    PolicyStatus,
    RiskLevel,
    SafeAction,
    TargetType,
)
from app.notifications.models import DeliveryStatus, NotificationResponse


@pytest.mark.asyncio
async def test_connector_test_executor_success():
    """Verify ConnectorTestExecutor calls test_connector and returns structured latency/status."""
    mock_conn_service = MagicMock()
    mock_conn_service.test_connector = AsyncMock(
        return_value={"status": "success", "status_code": 200, "latency_ms": 12.5, "url": "http://api/health"}
    )

    executor = ConnectorTestExecutor(mock_conn_service)
    assert executor.action_type == ActionType.TEST_CONNECTOR

    # Validation
    valid, _ = executor.validate_parameters({})
    assert valid
    invalid, err = executor.validate_parameters({"extra": 1})
    assert not invalid
    assert "no parameters" in err

    action = SafeAction(
        action_id="act-test",
        project_id="proj-1",
        incident_id=None,
        action_type=ActionType.TEST_CONNECTOR,
        target_type=TargetType.CONNECTOR,
        target_id="conn-123",
        parameters={},
        fingerprint="fp",
        requested_by_claim="admin",
        risk_level=RiskLevel.LOW,
        policy_status=PolicyStatus.ALLOWED,
        policy_denial_reason=None,
        approval_status=ApprovalStatus.APPROVED,
        execution_status=ExecutionStatus.EXECUTING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    result = await executor.execute(action)
    assert result.success
    assert result.data["status_code"] == 200
    mock_conn_service.test_connector.assert_called_once_with("conn-123")


@pytest.mark.asyncio
async def test_notification_retry_executor_atomic_success():
    """Verify NotificationRetryExecutor resets FAILED notification to PENDING."""
    mock_notif_service = MagicMock()
    mock_resp = MagicMock(spec=NotificationResponse)
    mock_resp.notification_id = "notif-999"
    mock_resp.delivery_status = DeliveryStatus.PENDING
    mock_resp.attempt_count = 0

    mock_notif_service.atomic_retry_notification.return_value = (True, mock_resp, None)

    executor = NotificationRetryExecutor(mock_notif_service)
    assert executor.action_type == ActionType.RETRY_NOTIFICATION

    action = SafeAction(
        action_id="act-notif",
        project_id="proj-1",
        incident_id=None,
        action_type=ActionType.RETRY_NOTIFICATION,
        target_type=TargetType.NOTIFICATION,
        target_id="notif-999",
        parameters={},
        fingerprint="fp",
        requested_by_claim="admin",
        risk_level=RiskLevel.LOW,
        policy_status=PolicyStatus.ALLOWED,
        policy_denial_reason=None,
        approval_status=ApprovalStatus.APPROVED,
        execution_status=ExecutionStatus.EXECUTING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    result = await executor.execute(action)
    assert result.success
    assert result.data["notification_id"] == "notif-999"
    assert result.data["delivery_status"] == "pending"


@pytest.mark.asyncio
async def test_notification_retry_executor_prerequisite_conflict():
    """Verify NotificationRetryExecutor raises PrerequisiteConflictError if not FAILED."""
    mock_notif_service = MagicMock()
    mock_resp = MagicMock(spec=NotificationResponse)
    mock_resp.delivery_status = DeliveryStatus.DELIVERED
    mock_notif_service.atomic_retry_notification.return_value = (False, mock_resp, DeliveryStatus.DELIVERED)

    executor = NotificationRetryExecutor(mock_notif_service)

    action = SafeAction(
        action_id="act-notif",
        project_id="proj-1",
        incident_id=None,
        action_type=ActionType.RETRY_NOTIFICATION,
        target_type=TargetType.NOTIFICATION,
        target_id="notif-999",
        parameters={},
        fingerprint="fp",
        requested_by_claim="admin",
        risk_level=RiskLevel.LOW,
        policy_status=PolicyStatus.ALLOWED,
        policy_denial_reason=None,
        approval_status=ApprovalStatus.APPROVED,
        execution_status=ExecutionStatus.EXECUTING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(PrerequisiteConflictError) as exc_info:
        await executor.execute(action)

    assert "no longer in FAILED state" in str(exc_info.value)
    assert exc_info.value.current_state == "delivered"
