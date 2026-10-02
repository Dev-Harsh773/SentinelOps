"""Tests for SqliteConnectorStore, schema constraints, foreign keys, cascades, and dedup log."""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pytest

from app.connectors.models import (
    Connector,
    ConnectorConfig,
    ConnectorHealth,
    ConnectorStatus,
    ConnectorType,
    OperationalStatus,
    TargetStatus,
)
from app.connectors.store import (
    ConnectorNotFoundError,
    DuplicateConnectorIdError,
    SqliteConnectorStore,
)
from app.projects.models import Project, ProjectStatus
from app.projects.storage import (
    ProjectHasActiveConnectorsError,
    ProjectNotFoundError,
    SqliteProjectStore,
)


@pytest.fixture
def test_db_path(tmp_path: Path) -> str:
    """Provide an isolated temporary SQLite database path."""
    return str(tmp_path / "sentinelops_test.db")


@pytest.fixture
def project_store(test_db_path: str) -> SqliteProjectStore:
    store = SqliteProjectStore(db_path=test_db_path)
    yield store
    store.close()


@pytest.fixture
def connector_store(test_db_path: str) -> SqliteConnectorStore:
    store = SqliteConnectorStore(db_path=test_db_path)
    yield store
    store.close()


def _create_sample_project(project_store: SqliteProjectStore, project_id: str = "proj-alpha") -> Project:
    now = datetime.now(timezone.utc)
    proj = Project(
        project_id=project_id,
        name="Alpha Project",
        workspace_path=f"D:/sample/{project_id}",
        normalized_path=f"d:/sample/{project_id}",
        is_git=False,
        status=ProjectStatus.READY,
        created_at=now,
        updated_at=now,
    )
    return project_store.create_project(proj)


def test_connector_crud_and_health_lifecycle(
    project_store: SqliteProjectStore, connector_store: SqliteConnectorStore
) -> None:
    _create_sample_project(project_store, "proj-1")
    now = datetime.now(timezone.utc)

    # 1. Create connector
    connector = Connector(
        connector_id="conn-1",
        project_id="proj-1",
        name="GitHub Webhook",
        connector_type=ConnectorType.WEBHOOK,
        config=ConnectorConfig(auth_secret="super-secret-key"),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    created = connector_store.create_connector(connector)
    assert created.connector_id == "conn-1"
    assert created.project_id == "proj-1"

    # 2. Verify initial health record automatically created
    health = connector_store.get_health("conn-1")
    assert health is not None
    assert health.connector_id == "conn-1"
    assert health.operational_status == OperationalStatus.HEALTHY
    assert health.target_status == TargetStatus.UNKNOWN

    # 3. Get connector
    fetched = connector_store.get_connector("conn-1")
    assert fetched is not None
    assert fetched.name == "GitHub Webhook"
    assert fetched.config.auth_secret == "super-secret-key"

    # 4. Update connector
    updated_connector = Connector(
        connector_id="conn-1",
        project_id="proj-1",
        name="GitHub Webhook Updated",
        connector_type=ConnectorType.WEBHOOK,
        config=ConnectorConfig(auth_secret="new-secret-key"),
        status=ConnectorStatus.DISABLED,
        created_at=now,
        updated_at=datetime.now(timezone.utc),
    )
    connector_store.update_connector(updated_connector)
    refetched = connector_store.get_connector("conn-1")
    assert refetched.name == "GitHub Webhook Updated"
    assert refetched.status == ConnectorStatus.DISABLED
    assert refetched.config.auth_secret == "new-secret-key"

    # 5. List connectors
    listed = connector_store.list_connectors(project_id="proj-1")
    assert len(listed) == 1
    assert listed[0].connector_id == "conn-1"

    # 6. Delete connector
    deleted = connector_store.delete_connector("conn-1")
    assert deleted is True
    assert connector_store.get_connector("conn-1") is None
    assert connector_store.get_health("conn-1") is None


def test_create_connector_unknown_project_fails(connector_store: SqliteConnectorStore) -> None:
    now = datetime.now(timezone.utc)
    connector = Connector(
        connector_id="conn-orphan",
        project_id="non-existent-project",
        name="Orphan Connector",
        connector_type=ConnectorType.WEBHOOK,
        config=ConnectorConfig(),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    with pytest.raises(ProjectNotFoundError):
        connector_store.create_connector(connector)


def test_foreign_key_on_delete_restrict_prevents_project_deletion(
    project_store: SqliteProjectStore, connector_store: SqliteConnectorStore
) -> None:
    _create_sample_project(project_store, "proj-restricted")
    now = datetime.now(timezone.utc)

    connector = Connector(
        connector_id="conn-child",
        project_id="proj-restricted",
        name="Child Connector",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(url="http://127.0.0.1:8080/health"),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(connector)

    # Attempting to delete the project must fail with ProjectHasActiveConnectorsError due to ON DELETE RESTRICT
    with pytest.raises(ProjectHasActiveConnectorsError):
        project_store.delete_project("proj-restricted")

    # Project still exists
    assert project_store.get_project("proj-restricted") is not None

    # Removing connector allows project deletion
    connector_store.delete_connector("conn-child")
    deleted = project_store.delete_project("proj-restricted")
    assert deleted is True
    assert project_store.get_project("proj-restricted") is None


def test_connector_delete_cascades_to_dedup_and_health(
    project_store: SqliteProjectStore, connector_store: SqliteConnectorStore
) -> None:
    _create_sample_project(project_store, "proj-cascade")
    now = datetime.now(timezone.utc)

    connector = Connector(
        connector_id="conn-cascade",
        project_id="proj-cascade",
        name="Cascade Test",
        connector_type=ConnectorType.WEBHOOK,
        config=ConnectorConfig(),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(connector)

    # Record dedup
    connector_store.record_dedup("conn-cascade", "evt-ext-100", now)
    assert connector_store.has_dedup_record("conn-cascade", "evt-ext-100") is True

    # Delete connector
    connector_store.delete_connector("conn-cascade")

    # Dedup and health rows must be gone
    assert connector_store.has_dedup_record("conn-cascade", "evt-ext-100") is False
    assert connector_store.get_health("conn-cascade") is None


def test_dedup_queries(project_store: SqliteProjectStore, connector_store: SqliteConnectorStore) -> None:
    _create_sample_project(project_store, "proj-dedup")
    now = datetime.now(timezone.utc)

    connector = Connector(
        connector_id="conn-dedup",
        project_id="proj-dedup",
        name="Dedup Test",
        connector_type=ConnectorType.WEBHOOK,
        config=ConnectorConfig(),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(connector)

    assert connector_store.has_dedup_record("conn-dedup", "event-abc") is False
    connector_store.record_dedup("conn-dedup", "event-abc", now)
    assert connector_store.has_dedup_record("conn-dedup", "event-abc") is True
    assert connector_store.has_dedup_record("conn-dedup", "event-xyz") is False
