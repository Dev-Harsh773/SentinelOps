"""Domain models and schemas for SentinelOps Notifications subsystem."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import uuid

from pydantic import BaseModel, Field, field_validator

from app.incidents.models import Severity


class NotificationChannel(str, Enum):
    """Supported notification delivery mechanisms."""

    WEBHOOK = "webhook"
    LOCAL_FEED = "local_feed"


class DeliveryStatus(str, Enum):
    """Delivery lifecycle states for notifications."""

    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"


class ReadStatus(str, Enum):
    """User read/acknowledgement states for notifications."""

    UNREAD = "unread"
    READ = "read"


class NotificationType(str, Enum):
    """Categories of event notifications."""

    INCIDENT_CREATED = "incident_created"
    INCIDENT_STATUS_CHANGED = "incident_status_changed"
    CONNECTOR_OPERATIONAL_DEGRADED = "connector_operational_degraded"
    CONNECTOR_OPERATIONAL_RECOVERED = "connector_operational_recovered"


def sanitize_webhook_recipient(url: str) -> str:
    """Produce a safe display recipient masking sensitive paths and query parameters.
    
    Example:
        https://hooks.slack.com/services/T00/B00/X123 -> https://hooks.slack.com/<redacted>
    """
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc
        if "@" in netloc:
            # Strip user:pass if present
            netloc = netloc.split("@")[-1]
        return f"{scheme}://{netloc}/<redacted>"
    except Exception:
        return "https://<redacted>"


class WebhookDestinationConfig(BaseModel):
    """Configuration schema for webhook delivery."""

    url: str
    auth_secret: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        clean = v.strip()
        if not (clean.startswith("http://") or clean.startswith("https://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        return clean


class SubscriptionCreateRequest(BaseModel):
    """Payload to create a project-scoped notification subscription."""

    project_id: str
    name: str
    channel: NotificationChannel
    destination_config: Dict[str, Any] = Field(default_factory=dict)
    min_severity: Severity = Severity.LOW
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Subscription name cannot be blank")
        return clean


class SubscriptionUpdateRequest(BaseModel):
    """Payload to partially update a notification subscription."""

    name: Optional[str] = None
    destination_config: Optional[Dict[str, Any]] = None
    min_severity: Optional[Severity] = None
    enabled: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Subscription name cannot be blank")
            return clean
        return v


class SubscriptionResponse(BaseModel):
    """API representation of a notification subscription with secrets masked."""

    subscription_id: str
    project_id: str
    name: str
    channel: NotificationChannel
    destination_config: Dict[str, Any]
    min_severity: Severity
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SubscriptionTestResponse(BaseModel):
    """Diagnostic response from testing a subscription destination."""

    success: bool
    status_code: Optional[int] = None
    latency_ms: float
    error: Optional[str] = None
    subscription_enabled: bool


class Notification(BaseModel):
    """Durable notification domain entity."""

    notification_id: str
    project_id: str
    incident_id: Optional[str] = None
    subscription_id: Optional[str] = None
    notification_type: NotificationType
    severity: Severity
    title: str
    message: str
    payload: Dict[str, Any]
    delivery_config: Optional[Dict[str, Any]] = None
    channel: NotificationChannel
    recipient: str
    delivery_status: DeliveryStatus
    read_status: ReadStatus = ReadStatus.UNREAD
    attempt_count: int = 0
    next_attempt_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    dedup_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class NotificationResponse(BaseModel):
    """API representation of a notification in the feed."""

    notification_id: str
    project_id: str
    incident_id: Optional[str] = None
    subscription_id: Optional[str] = None
    notification_type: NotificationType
    severity: Severity
    title: str
    message: str
    payload: Dict[str, Any]
    channel: NotificationChannel
    recipient: str
    delivery_status: DeliveryStatus
    read_status: ReadStatus
    attempt_count: int
    next_attempt_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
