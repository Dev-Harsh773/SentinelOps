"""Unit tests for NotificationService domain logic and lifecycle integration."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.connectors.models import OperationalStatus
from app.incidents.models import Incident, IncidentStatus, Severity
from app.notifications.models import (
    DeliveryStatus,
    NotificationChannel,
    NotificationType,
    ReadStatus,
    SubscriptionCreateRequest,
    SubscriptionUpdateRequest,
)
from app.notifications.service import NotificationConflictError, NotificationService
from app.notifications.store import SqliteNotificationStore
from app.projects.models import Project, ProjectStatus
from app.projects.storage import SqliteProjectStore


@pytest.fixture
def service_env(tmp_path: Path):
    db_file = str(tmp_path / "sentinelops_test.db")
    project_store = SqliteProjectStore(db_path=db_file)
    notif_store = SqliteNotificationStore(db_path=db_file)
    service = NotificationService(store=notif_store, project_store=project_store)

    now = datetime.now(timezone.utc)
    proj = Project(
        project_id="proj-alpha",
        name="Alpha Project",
        description="Test project",
        workspace_path=str(tmp_path / "workspace_alpha"),
        normalized_path=str((tmp_path / "workspace_alpha").resolve()).lower(),
        is_git=False,
        status=ProjectStatus.READY,
        created_at=now,
        updated_at=now,
    )
    project_store.create_project(proj)

    yield service, notif_store

    notif_store.close()
    project_store.close()


def test_incident_created_generates_notifications(service_env):
    service, notif_store = service_env
    # Register local feed and webhook subscriptions
    sub1 = service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Feed Sub",
            channel=NotificationChannel.LOCAL_FEED,
            min_severity=Severity.LOW,
        )
    )
    sub2 = service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Webhook Sub",
            channel=NotificationChannel.WEBHOOK,
            destination_config={"url": "https://hooks.example.com/alerts"},
            min_severity=Severity.HIGH,
        )
    )

    now = datetime.now(timezone.utc)
    incident = Incident(
        id="inc-101",
        title="Database Latency Spike",
        summary="DB latency > 500ms",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="db-service",
        environment="production",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )

    # Trigger observer
    service.on_incident_created(incident)

    notifs = service.list_notifications(project_id="proj-alpha")
    assert len(notifs) == 2

    feed_notif = next(n for n in notifs if n.channel == NotificationChannel.LOCAL_FEED)
    assert feed_notif.delivery_status == DeliveryStatus.DELIVERED
    assert feed_notif.read_status == ReadStatus.UNREAD
    assert feed_notif.title == "Incident Created: Database Latency Spike"

    webhook_notif = next(n for n in notifs if n.channel == NotificationChannel.WEBHOOK)
    assert webhook_notif.delivery_status == DeliveryStatus.PENDING
    assert webhook_notif.recipient == "https://hooks.example.com/<redacted>"
    assert webhook_notif.next_attempt_at is not None


def test_severity_threshold_filtering(service_env):
    service, notif_store = service_env
    service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Critical Alert",
            channel=NotificationChannel.LOCAL_FEED,
            min_severity=Severity.CRITICAL,
        )
    )

    now = datetime.now(timezone.utc)
    incident = Incident(
        id="inc-low",
        title="Minor Log Flap",
        summary="Low severity",
        severity=Severity.LOW,
        status=IncidentStatus.OPEN,
        service="api-service",
        environment="production",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )

    service.on_incident_created(incident)
    assert len(service.list_notifications(project_id="proj-alpha")) == 0


def test_disabled_subscription_suppresses_notification(service_env):
    service, notif_store = service_env
    service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Disabled Webhook",
            channel=NotificationChannel.WEBHOOK,
            destination_config={"url": "https://hooks.example.com/alerts"},
            min_severity=Severity.LOW,
            enabled=False,
        )
    )

    now = datetime.now(timezone.utc)
    incident = Incident(
        id="inc-disabled-test",
        title="Incident Test",
        summary="Summary",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="svc",
        environment="prod",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )

    service.on_incident_created(incident)
    assert len(service.list_notifications(project_id="proj-alpha")) == 0


def test_duplicate_incident_event_suppression(service_env):
    service, notif_store = service_env
    service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Feed",
            channel=NotificationChannel.LOCAL_FEED,
            min_severity=Severity.LOW,
        )
    )

    now = datetime.now(timezone.utc)
    incident = Incident(
        id="inc-repeat",
        title="Repeat Event",
        summary="Summary",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="svc",
        environment="prod",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )

    # First event -> 1 notification
    service.on_incident_created(incident)
    assert len(service.list_notifications(project_id="proj-alpha")) == 1

    # Replaying the exact identical creation event on the same incident -> suppressed via dedup_key
    service.on_incident_created(incident)
    assert len(service.list_notifications(project_id="proj-alpha")) == 1


def test_incident_status_change_notifications(service_env):
    service, notif_store = service_env
    service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Feed",
            channel=NotificationChannel.LOCAL_FEED,
            min_severity=Severity.LOW,
        )
    )

    now = datetime.now(timezone.utc)
    incident = Incident(
        id="inc-status-test",
        title="Database Timeout",
        summary="Summary",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="db",
        environment="prod",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )

    # 1. Transition OPEN -> INVESTIGATING is internal triage: NO notification generated
    service.on_incident_status_changed(incident, old_status=IncidentStatus.OPEN, new_status=IncidentStatus.INVESTIGATING)
    assert len(service.list_notifications(project_id="proj-alpha")) == 0

    # 2. Transition INVESTIGATING -> RESOLVED generates notification
    service.on_incident_status_changed(incident, old_status=IncidentStatus.INVESTIGATING, new_status=IncidentStatus.RESOLVED)
    notifs = service.list_notifications(project_id="proj-alpha")
    assert len(notifs) == 1
    assert notifs[0].notification_type == NotificationType.INCIDENT_STATUS_CHANGED
    assert "Resolved" in notifs[0].title

    # 3. Transition RESOLVED -> CLOSED generates notification
    service.on_incident_status_changed(incident, old_status=IncidentStatus.RESOLVED, new_status=IncidentStatus.CLOSED)
    notifs = service.list_notifications(project_id="proj-alpha")
    assert len(notifs) == 2
    assert any("Closed" in n.title for n in notifs)
    assert any("Resolved" in n.title for n in notifs)


def test_connector_operational_transition_notifications(service_env):
    service, notif_store = service_env
    service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Feed",
            channel=NotificationChannel.LOCAL_FEED,
            min_severity=Severity.LOW,
        )
    )

    now1 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
    # 1. Operational degradation (HEALTHY -> ERRORED): emits HIGH severity
    service.on_connector_operational_transition(
        connector_id="conn-1",
        project_id="proj-alpha",
        old_status=OperationalStatus.HEALTHY,
        new_status=OperationalStatus.ERRORED,
        transition_time=now1,
        error_message="SQLite database locked",
    )
    notifs = service.list_notifications(project_id="proj-alpha")
    assert len(notifs) == 1
    assert notifs[0].notification_type == NotificationType.CONNECTOR_OPERATIONAL_DEGRADED
    assert notifs[0].severity == Severity.HIGH

    # 2. Repeated poll remaining in ERRORED: no transition -> NO new notification
    service.on_connector_operational_transition(
        connector_id="conn-1",
        project_id="proj-alpha",
        old_status=OperationalStatus.ERRORED,
        new_status=OperationalStatus.ERRORED,
        transition_time=now1,
        error_message="SQLite database locked again",
    )
    assert len(service.list_notifications(project_id="proj-alpha")) == 1

    # 3. Operational recovery (ERRORED -> HEALTHY): emits LOW severity
    now2 = datetime(2026, 10, 2, 12, 5, 0, tzinfo=timezone.utc)
    service.on_connector_operational_transition(
        connector_id="conn-1",
        project_id="proj-alpha",
        old_status=OperationalStatus.ERRORED,
        new_status=OperationalStatus.HEALTHY,
        transition_time=now2,
    )
    notifs = service.list_notifications(project_id="proj-alpha")
    assert len(notifs) == 2
    assert notifs[0].notification_type == NotificationType.CONNECTOR_OPERATIONAL_RECOVERED
    assert notifs[0].severity == Severity.LOW


def test_manual_retry_behavior(service_env):
    service, notif_store = service_env
    now = datetime.now(timezone.utc)
    notif = service._store.create_notification(
        service._build_incident_notification(
            incident=Incident(
                id="inc-retry",
                title="Retry Test",
                summary="Sum",
                severity=Severity.HIGH,
                status=IncidentStatus.OPEN,
                service="svc",
                environment="prod",
                created_at=now,
                updated_at=now,
                project_id="proj-alpha",
            ),
            sub={
                "subscription_id": None,
                "channel": NotificationChannel.WEBHOOK,
                "destination_config": {"url": "https://hooks.example.com"},
            },
            notification_type=NotificationType.INCIDENT_CREATED,
            title="Title",
            message="Msg",
            dedup_key="dedup-retry",
            now=now,
        )
    )

    # 1. PENDING -> 409
    with pytest.raises(NotificationConflictError) as exc_info:
        service.retry_notification(notif.notification_id)
    assert "currently pending or delivering" in str(exc_info.value)

    # 2. Mark DELIVERED -> 409
    service._store.update_delivery_outcome(
        notification_id=notif.notification_id,
        delivery_status=DeliveryStatus.DELIVERED,
        delivered_at=now,
        now=now,
    )
    with pytest.raises(NotificationConflictError) as exc_info:
        service.retry_notification(notif.notification_id)
    assert "already delivered" in str(exc_info.value)

    # 3. Mark FAILED -> retry succeeds and resets to PENDING
    service._store.update_delivery_outcome(
        notification_id=notif.notification_id,
        delivery_status=DeliveryStatus.FAILED,
        failure_reason="Permanent connection drop",
        now=now,
    )
    retried = service.retry_notification(notif.notification_id)
    assert retried.delivery_status == DeliveryStatus.PENDING
    assert retried.attempt_count == 0
    assert retried.next_attempt_at is not None
    assert retried.failure_reason is None


def test_immutable_delivery_snapshot_preservation(service_env):
    service, notif_store = service_env
    sub = service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Initial Config",
            channel=NotificationChannel.WEBHOOK,
            destination_config={"url": "https://hooks.example.com/v1", "auth_secret": "secret123"},
        )
    )

    now = datetime.now(timezone.utc)
    incident = Incident(
        id="inc-snap",
        title="Snapshot Test",
        summary="Sum",
        severity=Severity.HIGH,
        status=IncidentStatus.OPEN,
        service="svc",
        environment="prod",
        created_at=now,
        updated_at=now,
        project_id="proj-alpha",
    )
    service.on_incident_created(incident)

    notifs = notif_store.list_notifications(project_id="proj-alpha")
    assert len(notifs) == 1
    assert notifs[0].delivery_config["url"] == "https://hooks.example.com/v1"

    # Now update subscription URL to v2
    service.update_subscription(
        sub.subscription_id,
        SubscriptionUpdateRequest(destination_config={"url": "https://hooks.example.com/v2"}),
    )

    # Existing notification's delivery_config snapshot is IMMUTABLE and untouched!
    notif_recheck = notif_store.get_notification(notifs[0].notification_id)
    assert notif_recheck.delivery_config["url"] == "https://hooks.example.com/v1"


def test_duplicate_listener_registration_and_reset(service_env):
    service, notif_store = service_env
    from app.incidents.repository import InMemoryIncidentRepository
    from app.incidents.schemas import IncidentCreateRequest
    from app.incidents.service import IncidentService

    inc_repo = InMemoryIncidentRepository()
    inc_service = IncidentService(repository=inc_repo)

    # 1. Register listener multiple times -> exactly one listener remains
    inc_service.add_listener(service)
    inc_service.add_listener(service)
    assert len(inc_service._listeners) == 1

    # 2. Reset listeners
    inc_service.clear_listeners()
    assert len(inc_service._listeners) == 0

    # 3. Re-register after reset results in exactly one listener
    inc_service.add_listener(service)
    assert len(inc_service._listeners) == 1

    # 4. Create subscription
    service.create_subscription(
        SubscriptionCreateRequest(
            project_id="proj-alpha",
            name="Feed",
            channel=NotificationChannel.LOCAL_FEED,
            min_severity=Severity.LOW,
        )
    )

    # 5. Create incident through incident service
    created = inc_service.create_incident(
        IncidentCreateRequest(
            title="Listener Test Incident",
            summary="Testing single callback delivery",
            severity=Severity.HIGH,
            service="auth-service",
            environment="production",
            project_id="proj-alpha",
        )
    )

    # 6. Verify exactly one notification was generated (no duplicate callback)
    notifs = service.list_notifications(project_id="proj-alpha")
    assert len(notifs) == 1
    assert notifs[0].incident_id == created.id

