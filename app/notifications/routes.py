"""FastAPI routes for notification subscriptions and notification feed."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.notifications.dependencies import get_notification_service
from app.notifications.models import (
    DeliveryStatus,
    NotificationChannel,
    NotificationResponse,
    ReadStatus,
    SubscriptionCreateRequest,
    SubscriptionResponse,
    SubscriptionTestResponse,
    SubscriptionUpdateRequest,
)
from app.notifications.service import NotificationConflictError, NotificationService
from app.notifications.store import (
    DuplicateSubscriptionIdError,
    NotificationNotFoundError,
    SubscriptionNotFoundError,
)
from app.projects.storage import ProjectNotFoundError

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# -----------------------------------------------------------------------------
# Subscription Endpoints
# -----------------------------------------------------------------------------

@router.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new notification subscription",
)
def create_subscription(
    payload: SubscriptionCreateRequest,
    service: NotificationService = Depends(get_notification_service),
) -> SubscriptionResponse:
    """Register a new project-scoped notification subscription destination."""
    try:
        return service.create_subscription(payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DuplicateSubscriptionIdError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get(
    "/subscriptions",
    response_model=List[SubscriptionResponse],
    status_code=status.HTTP_200_OK,
    summary="List notification subscriptions",
)
def list_subscriptions(
    project_id: Optional[str] = Query(default=None, description="Filter subscriptions by project_id"),
    service: NotificationService = Depends(get_notification_service),
) -> List[SubscriptionResponse]:
    """Retrieve notification subscriptions with credentials masked."""
    return service.list_subscriptions(project_id=project_id)


@router.get(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get subscription by ID",
)
def get_subscription(
    subscription_id: str,
    service: NotificationService = Depends(get_notification_service),
) -> SubscriptionResponse:
    """Retrieve a single notification subscription by identifier."""
    try:
        return service.get_subscription(subscription_id)
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch(
    "/subscriptions/{subscription_id}",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update notification subscription",
)
def update_subscription(
    subscription_id: str,
    payload: SubscriptionUpdateRequest,
    service: NotificationService = Depends(get_notification_service),
) -> SubscriptionResponse:
    """Partially update subscription configuration. Preserves masked credentials."""
    try:
        return service.update_subscription(subscription_id, payload)
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete notification subscription",
)
def delete_subscription(
    subscription_id: str,
    service: NotificationService = Depends(get_notification_service),
) -> None:
    """Delete a notification subscription."""
    deleted = service.delete_subscription(subscription_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription '{subscription_id}' not found.",
        )


@router.post(
    "/subscriptions/{subscription_id}/test",
    response_model=SubscriptionTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute diagnostic ping on subscription destination",
)
async def test_subscription(
    subscription_id: str,
    service: NotificationService = Depends(get_notification_service),
) -> SubscriptionTestResponse:
    """Execute a single diagnostic delivery to the destination without persisting history."""
    try:
        return await service.test_subscription(subscription_id)
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# -----------------------------------------------------------------------------
# Notification Feed Endpoints
# -----------------------------------------------------------------------------

@router.get(
    "",
    response_model=List[NotificationResponse],
    status_code=status.HTTP_200_OK,
    summary="List notifications feed",
)
def list_notifications(
    project_id: Optional[str] = Query(default=None, description="Filter notifications by project_id"),
    read_status: Optional[ReadStatus] = Query(default=None, description="Filter by read status"),
    channel: Optional[NotificationChannel] = Query(default=None, description="Filter by delivery channel"),
    delivery_status: Optional[DeliveryStatus] = Query(default=None, description="Filter by delivery status"),
    limit: int = Query(default=50, ge=1, le=200, description="Max notifications to return"),
    offset: int = Query(default=0, ge=0, description="Query offset for pagination"),
    service: NotificationService = Depends(get_notification_service),
) -> List[NotificationResponse]:
    """Retrieve notifications feed. Preserves historical records even after project deletion."""
    return service.list_notifications(
        project_id=project_id,
        read_status=read_status,
        channel=channel,
        delivery_status=delivery_status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{notification_id}",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get notification by ID",
)
def get_notification(
    notification_id: str,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    """Retrieve a single notification record."""
    try:
        return service.get_notification(notification_id)
    except NotificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark notification as read",
)
def mark_notification_read(
    notification_id: str,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    """Update read status of a notification to 'read'."""
    try:
        return service.mark_notification_read(notification_id)
    except NotificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/mark-all-read",
    status_code=status.HTTP_200_OK,
    summary="Mark all notifications for project as read",
)
def mark_all_read(
    project_id: str = Query(..., description="Project identifier to mark all read"),
    service: NotificationService = Depends(get_notification_service),
) -> Dict[str, Any]:
    """Mark all unread notifications for a project as read."""
    return service.mark_all_read(project_id)


@router.post(
    "/{notification_id}/retry",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually retry a failed notification",
)
def retry_notification(
    notification_id: str,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    """Reset a failed notification to 'pending' to trigger delivery worker."""
    try:
        return service.retry_notification(notification_id)
    except NotificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except NotificationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc.message))
