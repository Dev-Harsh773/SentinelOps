"""Unit tests for SqliteNotificationStore.

Verifies:
- Production DB isolation (never touches runtime/sentinelops.db)
- Subscription CRUD operations and validation
- Foreign key ON DELETE RESTRICT on projects
- Preservation of notification history after project deletion
- Deduplication key uniqueness
- Atomic single-worker claim and next_attempt_at filtering
- Startup recovery of in-flight delivering records
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from app.incidents.models import Severity
from app.notifications.models import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationType,
    ReadStatus,
)
from app.notifications.store import (
    DuplicateSubscriptionIdError,
    NotificationNotFoundError,
    SqliteNotificationStore,
    SubscriptionNotFoundError,
)
from app.projects.models import Project, ProjectStatus
from app.projects.storage import (
    ProjectHasActiveConnectorsError,
    ProjectNotFoundError,
    SqliteProjectStore,
)


@pytest.fixture
def store_env(tmp_path: Path):
    db_file = str(tmp_path / "sentinelops_test.db")
    project_store = SqliteProjectStore(db_path=db_file)
    notif_store = SqliteNotificationStore(db_path=db_file)

    now = datetime.now(timezone.utc)
    # Register a base project
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

    yield project_store, notif_store

    notif_store.close()
    project_store.close()


def test_subscription_crud(store_env):
    _, notif_store = store_env
    now = datetime.now(timezone.utc)

    # 1. Create
    sub = notif_store.create_subscription(
        subscription_id="sub-1",
        project_id="proj-alpha",
        name="Slack Webhook",
        channel=NotificationChannel.WEBHOOK,
        destination_config={"url": "https://hooks.example.com/alerts", "timeout_seconds": 5.0},
        min_severity=Severity.HIGH,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    assert sub["subscription_id"] == "sub-1"
    assert sub["project_id"] == "proj-alpha"
    assert sub["name"] == "Slack Webhook"
    assert sub["min_severity"] == Severity.HIGH
    assert sub["enabled"] is True

    # 2. Get
    fetched = notif_store.get_subscription("sub-1")
    assert fetched["subscription_id"] == "sub-1"
    assert fetched["destination_config"]["timeout_seconds"] == 5.0

    # 3. List
    all_subs = notif_store.list_subscriptions()
    assert len(all_subs) == 1
    proj_subs = notif_store.list_subscriptions(project_id="proj-alpha")
    assert len(proj_subs) == 1
    empty_subs = notif_store.list_subscriptions(project_id="proj-nonexistent")
    assert len(empty_subs) == 0

    # 4. Update
    updated = notif_store.update_subscription(
        subscription_id="sub-1",
        name="Slack Webhook Renamed",
        min_severity=Severity.CRITICAL,
        enabled=False,
    )
    assert updated["name"] == "Slack Webhook Renamed"
    assert updated["min_severity"] == Severity.CRITICAL
    assert updated["enabled"] is False

    # 5. Delete
    deleted = notif_store.delete_subscription("sub-1")
    assert deleted is True
    with pytest.raises(SubscriptionNotFoundError):
        notif_store.get_subscription("sub-1")


def test_subscription_project_not_found(store_env):
    _, notif_store = store_env
    now = datetime.now(timezone.utc)
    with pytest.raises(ProjectNotFoundError):
        notif_store.create_subscription(
            subscription_id="sub-bad",
            project_id="proj-missing",
            name="Orphan Sub",
            channel=NotificationChannel.WEBHOOK,
            destination_config={"url": "https://hooks.example.com/alerts"},
            min_severity=Severity.LOW,
            enabled=True,
            created_at=now,
            updated_at=now,
        )


def test_subscription_duplicate_id(store_env):
    _, notif_store = store_env
    now = datetime.now(timezone.utc)
    notif_store.create_subscription(
        subscription_id="sub-dup",
        project_id="proj-alpha",
        name="First",
        channel=NotificationChannel.LOCAL_FEED,
        destination_config={},
        min_severity=Severity.LOW,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(DuplicateSubscriptionIdError):
        notif_store.create_subscription(
            subscription_id="sub-dup",
            project_id="proj-alpha",
            name="Second",
            channel=NotificationChannel.LOCAL_FEED,
            destination_config={},
            min_severity=Severity.LOW,
            enabled=True,
            created_at=now,
            updated_at=now,
        )


def test_project_fk_on_delete_restrict(store_env):
    project_store, notif_store = store_env
    now = datetime.now(timezone.utc)
    notif_store.create_subscription(
        subscription_id="sub-restrict",
        project_id="proj-alpha",
        name="Active Sub",
        channel=NotificationChannel.WEBHOOK,
        destination_config={"url": "https://hooks.example.com/alerts"},
        min_severity=Severity.LOW,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    # Attempting to delete project must fail with ProjectHasActiveConnectorsError (or alias)
    with pytest.raises(ProjectHasActiveConnectorsError) as exc_info:
        project_store.delete_project("proj-alpha")
    assert "dependent records exist" in str(exc_info.value)


def test_notification_history_survives_project_deletion(store_env):
    project_store, notif_store = store_env
    now = datetime.now(timezone.utc)
    notif_store.create_subscription(
        subscription_id="sub-hist",
        project_id="proj-alpha",
        name="Audit Sub",
        channel=NotificationChannel.LOCAL_FEED,
        destination_config={},
        min_severity=Severity.LOW,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    notif = Notification(
        notification_id="notif-1",
        project_id="proj-alpha",
        incident_id="inc-1",
        subscription_id="sub-hist",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Incident Opened",
        message="Failure occurred",
        payload={"service": "auth"},
        channel=NotificationChannel.LOCAL_FEED,
        recipient="local_feed",
        delivery_status=DeliveryStatus.DELIVERED,
        read_status=ReadStatus.UNREAD,
        delivered_at=now,
        dedup_key="dedup-1",
        created_at=now,
        updated_at=now,
    )
    notif_store.create_notification(notif)

    # 1. Delete subscription
    assert notif_store.delete_subscription("sub-hist") is True

    # 2. Delete project (now succeeds because subscriptions are gone)
    assert project_store.delete_project("proj-alpha") is True

    # 3. Notification history remains queryable by historical project_id!
    history = notif_store.list_notifications(project_id="proj-alpha")
    assert len(history) == 1
    assert history[0].notification_id == "notif-1"
    assert history[0].project_id == "proj-alpha"
    # subscription_id set to None via ON DELETE SET NULL
    assert history[0].subscription_id is None


def test_dedup_key_uniqueness(store_env):
    _, notif_store = store_env
    now = datetime.now(timezone.utc)
    notif1 = Notification(
        notification_id="notif-dedup-1",
        project_id="proj-alpha",
        incident_id="inc-1",
        subscription_id=None,
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Incident Opened",
        message="Failure occurred",
        payload={},
        channel=NotificationChannel.LOCAL_FEED,
        recipient="local_feed",
        delivery_status=DeliveryStatus.DELIVERED,
        dedup_key="unique-dedup-key",
        created_at=now,
        updated_at=now,
    )
    created1 = notif_store.create_notification(notif1)
    assert created1 is not None

    # Identical dedup_key with different notification_id
    notif2 = Notification(
        notification_id="notif-dedup-2",
        project_id="proj-alpha",
        incident_id="inc-1",
        subscription_id=None,
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Incident Opened",
        message="Failure occurred",
        payload={},
        channel=NotificationChannel.LOCAL_FEED,
        recipient="local_feed",
        delivery_status=DeliveryStatus.DELIVERED,
        dedup_key="unique-dedup-key",
        created_at=now,
        updated_at=now,
    )
    created2 = notif_store.create_notification(notif2)
    assert created2 is None
    assert len(notif_store.list_notifications()) == 1


def test_atomic_single_worker_claim(store_env):
    _, notif_store = store_env
    now = datetime.now(timezone.utc)
    notif = Notification(
        notification_id="notif-claim-1",
        project_id="proj-alpha",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Incident Claim",
        message="Awaiting dispatch",
        payload={},
        delivery_config={"url": "https://hooks.example.com"},
        channel=NotificationChannel.WEBHOOK,
        recipient="https://hooks.example.com/<redacted>",
        delivery_status=DeliveryStatus.PENDING,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    notif_store.create_notification(notif)

    # First claim succeeds
    claimed1 = notif_store.claim_due_notifications(limit=5, now=now)
    assert len(claimed1) == 1
    assert claimed1[0].notification_id == "notif-claim-1"
    assert claimed1[0].delivery_status == DeliveryStatus.DELIVERING
    assert claimed1[0].attempt_count == 1

    # Concurrent second claim on same pending notification yields 0 records
    claimed2 = notif_store.claim_due_notifications(limit=5, now=now)
    assert len(claimed2) == 0


def test_durable_next_attempt_at_filtering(store_env):
    _, notif_store = store_env
    now = datetime.now(timezone.utc)
    future = now + timedelta(seconds=60)
    notif = Notification(
        notification_id="notif-future-1",
        project_id="proj-alpha",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Future Incident",
        message="Backoff active",
        payload={},
        delivery_config={"url": "https://hooks.example.com"},
        channel=NotificationChannel.WEBHOOK,
        recipient="https://hooks.example.com/<redacted>",
        delivery_status=DeliveryStatus.PENDING,
        next_attempt_at=future,
        created_at=now,
        updated_at=now,
    )
    notif_store.create_notification(notif)

    # Claiming at current time does not return future work
    claimed = notif_store.claim_due_notifications(limit=5, now=now)
    assert len(claimed) == 0

    # Claiming after future deadline returns it
    claimed_later = notif_store.claim_due_notifications(limit=5, now=future + timedelta(seconds=1))
    assert len(claimed_later) == 1
    assert claimed_later[0].notification_id == "notif-future-1"


def test_read_status_and_pagination(store_env):
    _, notif_store = store_env
    now = datetime.now(timezone.utc)

    for i in range(5):
        notif = Notification(
            notification_id=f"notif-read-{i}",
            project_id="proj-alpha",
            notification_type=NotificationType.INCIDENT_CREATED,
            severity=Severity.LOW,
            title=f"Notification {i}",
            message="Content",
            payload={},
            channel=NotificationChannel.LOCAL_FEED,
            recipient="local_feed",
            delivery_status=DeliveryStatus.DELIVERED,
            read_status=ReadStatus.UNREAD,
            delivered_at=now,
            created_at=now + timedelta(seconds=i),
            updated_at=now + timedelta(seconds=i),
        )
        notif_store.create_notification(notif)

    # Pagination: limit 2, offset 0
    page1 = notif_store.list_notifications(limit=2, offset=0)
    assert len(page1) == 2
    # Offset 2
    page2 = notif_store.list_notifications(limit=2, offset=2)
    assert len(page2) == 2
    assert page1[0].notification_id != page2[0].notification_id

    # Mark single read
    updated = notif_store.mark_notification_read("notif-read-0", now=now)
    assert updated.read_status == ReadStatus.READ
    assert updated.read_at is not None

    unread = notif_store.list_notifications(read_status=ReadStatus.UNREAD)
    assert len(unread) == 4

    # Mark all read
    marked_count = notif_store.mark_all_read(project_id="proj-alpha", now=now)
    assert marked_count == 4
    all_read = notif_store.list_notifications(read_status=ReadStatus.UNREAD)
    assert len(all_read) == 0


def test_recover_in_flight_on_startup(store_env):
    _, notif_store = store_env
    now = datetime.now(timezone.utc)

    # 1. Delivering with attempt 1 -> should recover to pending
    notif1 = Notification(
        notification_id="notif-crash-1",
        project_id="proj-alpha",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Interrupted Delivery",
        message="Body",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="https://hooks.example.com/<redacted>",
        delivery_status=DeliveryStatus.DELIVERING,
        attempt_count=1,
        created_at=now,
        updated_at=now,
    )
    notif_store.create_notification(notif1)

    # 2. Delivering with attempt 3 -> should mark failed
    notif2 = Notification(
        notification_id="notif-crash-2",
        project_id="proj-alpha",
        notification_type=NotificationType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        title="Max Attempt Delivery",
        message="Body",
        payload={},
        channel=NotificationChannel.WEBHOOK,
        recipient="https://hooks.example.com/<redacted>",
        delivery_status=DeliveryStatus.DELIVERING,
        attempt_count=3,
        created_at=now,
        updated_at=now,
    )
    notif_store.create_notification(notif2)

    recovered = notif_store.recover_in_flight_on_startup(now=now)
    assert recovered == 1

    rec1 = notif_store.get_notification("notif-crash-1")
    assert rec1.delivery_status == DeliveryStatus.PENDING
    assert rec1.attempt_count == 1  # Preserved!
    assert "Process restarted" in (rec1.failure_reason or "")

    rec2 = notif_store.get_notification("notif-crash-2")
    assert rec2.delivery_status == DeliveryStatus.FAILED
    assert rec2.attempt_count == 3
