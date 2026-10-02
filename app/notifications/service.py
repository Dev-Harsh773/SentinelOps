"""Business logic service for notifications and subscriptions."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from app.connectors.models import OperationalStatus
from app.connectors.redaction import is_secret_masked, mask_secret, redact_secrets
from app.incidents.models import Incident, IncidentStatus, Severity
from app.notifications.delivery import NotificationDeliveryRuntime
from app.notifications.models import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationResponse,
    NotificationType,
    ReadStatus,
    SubscriptionCreateRequest,
    SubscriptionResponse,
    SubscriptionTestResponse,
    SubscriptionUpdateRequest,
    sanitize_webhook_recipient,
)
from app.notifications.store import (
    NotificationNotFoundError,
    SqliteNotificationStore,
    SubscriptionNotFoundError,
)
from app.projects.storage import ProjectNotFoundError, SqliteProjectStore

logger = logging.getLogger("sentinelops.notifications.service")

SEVERITY_ORDER: Dict[Severity, int] = {
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class NotificationConflictError(Exception):
    """Raised when an operation cannot be completed due to conflicting state."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotificationService:
    """Coordinates notification subscription management, event processing, and feed state."""

    def __init__(
        self,
        store: SqliteNotificationStore,
        project_store: SqliteProjectStore,
        runtime: Optional[NotificationDeliveryRuntime] = None,
    ) -> None:
        self._store = store
        self._project_store = project_store
        self._runtime = runtime

    def set_runtime(self, runtime: NotificationDeliveryRuntime) -> None:
        """Bind delivery runtime after dependency assembly."""
        self._runtime = runtime

    # -------------------------------------------------------------------------
    # Subscription Management
    # -------------------------------------------------------------------------

    def create_subscription(self, payload: SubscriptionCreateRequest) -> SubscriptionResponse:
        """Create a new notification subscription bound to an existing project."""
        # 1. Enforce that project exists
        self._project_store.get_project(payload.project_id)

        # 2. Validate webhook URL format if channel is webhook
        dest_config = payload.destination_config or {}
        if payload.channel == NotificationChannel.WEBHOOK:
            url = dest_config.get("url", "").strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError("Webhook URL must start with http:// or https://")

        now = datetime.now(timezone.utc)
        sub_id = str(uuid.uuid4())

        record = self._store.create_subscription(
            subscription_id=sub_id,
            project_id=payload.project_id,
            name=payload.name,
            channel=payload.channel,
            destination_config=dest_config,
            min_severity=payload.min_severity,
            enabled=payload.enabled,
            created_at=now,
            updated_at=now,
        )
        return self._to_subscription_response(record)

    def get_subscription(self, subscription_id: str) -> SubscriptionResponse:
        """Fetch subscription by ID with masked secrets."""
        record = self._store.get_subscription(subscription_id)
        return self._to_subscription_response(record)

    def list_subscriptions(self, project_id: Optional[str] = None) -> List[SubscriptionResponse]:
        """List subscriptions with masked secrets."""
        records = self._store.list_subscriptions(project_id=project_id)
        return [self._to_subscription_response(r) for r in records]

    def update_subscription(
        self, subscription_id: str, payload: SubscriptionUpdateRequest
    ) -> SubscriptionResponse:
        """Update subscription fields, preserving masked secrets."""
        existing = self._store.get_subscription(subscription_id)
        existing_config = existing["destination_config"]

        new_config = None
        if payload.destination_config is not None:
            new_config = dict(payload.destination_config)
            # If payload submitted masked secret, retain the original stored secret
            submitted_secret = new_config.get("auth_secret")
            if is_secret_masked(submitted_secret):
                new_config["auth_secret"] = existing_config.get("auth_secret")

            # Preserve any masked headers
            if "headers" in new_config and isinstance(new_config["headers"], dict):
                orig_headers = existing_config.get("headers", {})
                for hk, hv in new_config["headers"].items():
                    if is_secret_masked(hv) and hk in orig_headers:
                        new_config["headers"][hk] = orig_headers[hk]

        now = datetime.now(timezone.utc)
        updated = self._store.update_subscription(
            subscription_id=subscription_id,
            name=payload.name,
            destination_config=new_config,
            min_severity=payload.min_severity,
            enabled=payload.enabled,
            updated_at=now,
        )
        return self._to_subscription_response(updated)

    def delete_subscription(self, subscription_id: str) -> bool:
        """Delete subscription by ID."""
        return self._store.delete_subscription(subscription_id)

    async def test_subscription(self, subscription_id: str) -> SubscriptionTestResponse:
        """Execute a diagnostic ping for a webhook subscription without mutating state."""
        sub = self._store.get_subscription(subscription_id)
        if sub["channel"] != NotificationChannel.WEBHOOK:
            raise ValueError("Test diagnostic is only supported for webhook subscriptions.")

        if not self._runtime:
            raise RuntimeError("Notification delivery runtime is not initialized.")

        cfg = sub["destination_config"]
        url = cfg.get("url", "")
        auth_secret = cfg.get("auth_secret")
        headers = cfg.get("headers", {})
        timeout_seconds = float(cfg.get("timeout_seconds", 10.0))

        return await self._runtime.send_diagnostic_ping(
            url=url,
            auth_secret=auth_secret,
            headers=headers,
            timeout_seconds=timeout_seconds,
            subscription_enabled=sub["enabled"],
        )

    # -------------------------------------------------------------------------
    # Lifecycle Observers (Event-Loop Safe)
    # -------------------------------------------------------------------------

    def on_incident_created(self, incident: Incident) -> None:
        """Synchronously evaluate subscriptions and persist notification records for a new incident."""
        try:
            subs = self._store.list_subscriptions(project_id=incident.project_id)
            inc_sev_level = SEVERITY_ORDER.get(incident.severity, 1)

            now = datetime.now(timezone.utc)
            should_wake = False

            for sub in subs:
                if not sub["enabled"]:
                    continue
                min_sev_level = SEVERITY_ORDER.get(sub["min_severity"], 1)
                if inc_sev_level < min_sev_level:
                    continue

                dedup_key = f"{incident.project_id}:incident:{incident.id}:created:{sub['subscription_id']}"
                notif = self._build_incident_notification(
                    incident=incident,
                    sub=sub,
                    notification_type=NotificationType.INCIDENT_CREATED,
                    title=f"Incident Created: {incident.title}",
                    message=incident.summary,
                    dedup_key=dedup_key,
                    now=now,
                )
                created = self._store.create_notification(notif)
                if created and created.channel == NotificationChannel.WEBHOOK:
                    should_wake = True

            if should_wake and self._runtime:
                self._runtime.wake()

        except Exception as exc:
            logger.error(
                "Error processing on_incident_created notification for incident %s: %s",
                incident.id,
                exc,
                exc_info=True,
            )

    def on_incident_status_changed(
        self, incident: Incident, old_status: IncidentStatus, new_status: IncidentStatus
    ) -> None:
        """Synchronously process incident resolution or closure notifications."""
        # Only transitions to RESOLVED or CLOSED generate notifications
        if new_status not in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
            return

        try:
            subs = self._store.list_subscriptions(project_id=incident.project_id)
            inc_sev_level = SEVERITY_ORDER.get(incident.severity, 1)

            now = datetime.now(timezone.utc)
            should_wake = False

            action_label = "Resolved" if new_status == IncidentStatus.RESOLVED else "Closed"

            for sub in subs:
                if not sub["enabled"]:
                    continue
                min_sev_level = SEVERITY_ORDER.get(sub["min_severity"], 1)
                if inc_sev_level < min_sev_level:
                    continue

                dedup_key = f"{incident.project_id}:incident:{incident.id}:status_{new_status.value}:{sub['subscription_id']}"
                notif = self._build_incident_notification(
                    incident=incident,
                    sub=sub,
                    notification_type=NotificationType.INCIDENT_STATUS_CHANGED,
                    title=f"Incident {action_label}: {incident.title}",
                    message=f"Incident '{incident.title}' transitioned from {old_status.value.upper()} to {new_status.value.upper()}.",
                    dedup_key=dedup_key,
                    now=now,
                )
                created = self._store.create_notification(notif)
                if created and created.channel == NotificationChannel.WEBHOOK:
                    should_wake = True

            if should_wake and self._runtime:
                self._runtime.wake()

        except Exception as exc:
            logger.error(
                "Error processing on_incident_status_changed for incident %s: %s",
                incident.id,
                exc,
                exc_info=True,
            )

    def on_connector_operational_transition(
        self,
        connector_id: str,
        project_id: str,
        old_status: OperationalStatus,
        new_status: OperationalStatus,
        transition_time: datetime,
        error_message: Optional[str] = None,
    ) -> None:
        """Synchronously process connector internal operational degradation or recovery notifications."""
        try:
            is_degraded = (
                old_status == OperationalStatus.HEALTHY and new_status == OperationalStatus.ERRORED
            )
            is_recovered = (
                old_status in (OperationalStatus.DEGRADED, OperationalStatus.ERRORED)
                and new_status == OperationalStatus.HEALTHY
            )

            if not (is_degraded or is_recovered):
                return

            severity = Severity.HIGH if is_degraded else Severity.LOW
            notif_type = (
                NotificationType.CONNECTOR_OPERATIONAL_DEGRADED
                if is_degraded
                else NotificationType.CONNECTOR_OPERATIONAL_RECOVERED
            )
            action_tag = "degraded" if is_degraded else "recovered"
            title = (
                f"Connector Operational Failure: {connector_id}"
                if is_degraded
                else f"Connector Operational Recovered: {connector_id}"
            )
            message = (
                f"Connector '{connector_id}' entered operational ERRORED state: {error_message or 'Internal error'}"
                if is_degraded
                else f"Connector '{connector_id}' recovered to HEALTHY operational state."
            )

            subs = self._store.list_subscriptions(project_id=project_id)
            event_sev_level = SEVERITY_ORDER[severity]
            should_wake = False
            ts_str = transition_time.isoformat()

            for sub in subs:
                if not sub["enabled"]:
                    continue
                min_sev_level = SEVERITY_ORDER.get(sub["min_severity"], 1)
                if event_sev_level < min_sev_level:
                    continue

                # Binding correction 1: exact transition timestamp in dedup key
                dedup_key = f"{project_id}:connector:{connector_id}:{action_tag}:{ts_str}:{sub['subscription_id']}"
                dest_cfg = sub["destination_config"]
                recipient = (
                    "local_feed"
                    if sub["channel"] == NotificationChannel.LOCAL_FEED
                    else sanitize_webhook_recipient(dest_cfg.get("url", ""))
                )

                notif = Notification(
                    notification_id=str(uuid.uuid4()),
                    project_id=project_id,
                    incident_id=None,
                    subscription_id=sub["subscription_id"],
                    notification_type=notif_type,
                    severity=severity,
                    title=title,
                    message=message,
                    payload={
                        "connector_id": connector_id,
                        "old_status": old_status.value,
                        "new_status": new_status.value,
                        "error_message": error_message,
                    },
                    delivery_config=dest_cfg if sub["channel"] == NotificationChannel.WEBHOOK else None,
                    channel=sub["channel"],
                    recipient=recipient,
                    delivery_status=(
                        DeliveryStatus.DELIVERED
                        if sub["channel"] == NotificationChannel.LOCAL_FEED
                        else DeliveryStatus.PENDING
                    ),
                    read_status=ReadStatus.UNREAD,
                    attempt_count=0,
                    next_attempt_at=(
                        transition_time if sub["channel"] == NotificationChannel.WEBHOOK else None
                    ),
                    delivered_at=(
                        transition_time if sub["channel"] == NotificationChannel.LOCAL_FEED else None
                    ),
                    dedup_key=dedup_key,
                    created_at=transition_time,
                    updated_at=transition_time,
                )
                created = self._store.create_notification(notif)
                if created and created.channel == NotificationChannel.WEBHOOK:
                    should_wake = True

            if should_wake and self._runtime:
                self._runtime.wake()

        except Exception as exc:
            logger.error(
                "Error processing connector operational notification for %s: %s",
                connector_id,
                exc,
                exc_info=True,
            )

    # -------------------------------------------------------------------------
    # Feed & Delivery Queries
    # -------------------------------------------------------------------------

    def list_notifications(
        self,
        project_id: Optional[str] = None,
        read_status: Optional[ReadStatus] = None,
        channel: Optional[NotificationChannel] = None,
        delivery_status: Optional[DeliveryStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[NotificationResponse]:
        """List notifications in feed.
        
        Binding correction 4: Does NOT require the project to still exist.
        Preserved historical notifications remain queryable.
        """
        records = self._store.list_notifications(
            project_id=project_id,
            read_status=read_status,
            channel=channel,
            delivery_status=delivery_status,
            limit=limit,
            offset=offset,
        )
        return [self._to_notification_response(r) for r in records]

    def get_notification(self, notification_id: str) -> NotificationResponse:
        """Fetch notification by ID."""
        notif = self._store.get_notification(notification_id)
        return self._to_notification_response(notif)

    def mark_notification_read(self, notification_id: str) -> NotificationResponse:
        """Mark single notification as read."""
        now = datetime.now(timezone.utc)
        updated = self._store.mark_notification_read(notification_id, now)
        return self._to_notification_response(updated)

    def mark_all_read(self, project_id: str) -> Dict[str, Any]:
        """Mark all unread notifications for a project as read."""
        now = datetime.now(timezone.utc)
        count = self._store.mark_all_read(project_id, now)
        return {"project_id": project_id, "marked_read_count": count}

    def retry_notification(self, notification_id: str) -> NotificationResponse:
        """Manually re-trigger delivery for a failed notification."""
        notif = self._store.get_notification(notification_id)
        if notif.delivery_status == DeliveryStatus.DELIVERED:
            raise NotificationConflictError(f"Notification '{notification_id}' is already delivered.")
        if notif.delivery_status in (DeliveryStatus.PENDING, DeliveryStatus.DELIVERING):
            raise NotificationConflictError(
                f"Notification '{notification_id}' is currently pending or delivering."
            )

        now = datetime.now(timezone.utc)
        updated = self._store.reset_for_manual_retry(notification_id, now)
        if self._runtime:
            self._runtime.wake()
        return self._to_notification_response(updated)

    # -------------------------------------------------------------------------
    # Helper Mappings
    # -------------------------------------------------------------------------

    def _build_incident_notification(
        self,
        incident: Incident,
        sub: Dict[str, Any],
        notification_type: NotificationType,
        title: str,
        message: str,
        dedup_key: str,
        now: datetime,
    ) -> Notification:
        dest_cfg = sub["destination_config"]
        recipient = (
            "local_feed"
            if sub["channel"] == NotificationChannel.LOCAL_FEED
            else sanitize_webhook_recipient(dest_cfg.get("url", ""))
        )
        return Notification(
            notification_id=str(uuid.uuid4()),
            project_id=incident.project_id,
            incident_id=incident.id,
            subscription_id=sub["subscription_id"],
            notification_type=notification_type,
            severity=incident.severity,
            title=title,
            message=message,
            payload={
                "service": incident.service,
                "environment": incident.environment,
                "incident_status": incident.status.value,
                "references": {
                    "incident_api_url": f"/incidents/{incident.id}",
                },
            },
            delivery_config=dest_cfg if sub["channel"] == NotificationChannel.WEBHOOK else None,
            channel=sub["channel"],
            recipient=recipient,
            delivery_status=(
                DeliveryStatus.DELIVERED
                if sub["channel"] == NotificationChannel.LOCAL_FEED
                else DeliveryStatus.PENDING
            ),
            read_status=ReadStatus.UNREAD,
            attempt_count=0,
            next_attempt_at=now if sub["channel"] == NotificationChannel.WEBHOOK else None,
            delivered_at=now if sub["channel"] == NotificationChannel.LOCAL_FEED else None,
            dedup_key=dedup_key,
            created_at=now,
            updated_at=now,
        )

    def _to_subscription_response(self, record: Dict[str, Any]) -> SubscriptionResponse:
        masked_config = dict(record["destination_config"])
        if "auth_secret" in masked_config and masked_config["auth_secret"]:
            masked_config["auth_secret"] = mask_secret(masked_config["auth_secret"])
        if "headers" in masked_config and isinstance(masked_config["headers"], dict):
            masked_headers = {}
            for hk, hv in masked_config["headers"].items():
                if any(k in hk.lower() for k in ("secret", "token", "key", "auth")):
                    masked_headers[hk] = mask_secret(hv)
                else:
                    masked_headers[hk] = hv
            masked_config["headers"] = masked_headers

        return SubscriptionResponse(
            subscription_id=record["subscription_id"],
            project_id=record["project_id"],
            name=record["name"],
            channel=record["channel"],
            destination_config=masked_config,
            min_severity=record["min_severity"],
            enabled=record["enabled"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )

    def _to_notification_response(self, notif: Notification) -> NotificationResponse:
        return NotificationResponse(
            notification_id=notif.notification_id,
            project_id=notif.project_id,
            incident_id=notif.incident_id,
            subscription_id=notif.subscription_id,
            notification_type=notif.notification_type,
            severity=notif.severity,
            title=notif.title,
            message=notif.message,
            payload=notif.payload,
            channel=notif.channel,
            recipient=notif.recipient,
            delivery_status=notif.delivery_status,
            read_status=notif.read_status,
            attempt_count=notif.attempt_count,
            next_attempt_at=notif.next_attempt_at,
            last_attempt_at=notif.last_attempt_at,
            delivered_at=notif.delivered_at,
            read_at=notif.read_at,
            failure_reason=notif.failure_reason,
            created_at=notif.created_at,
            updated_at=notif.updated_at,
        )
