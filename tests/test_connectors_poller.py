"""Tests for ConnectorPollerRuntime, target health vs operational failure classification."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
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
from app.connectors.poller import ConnectorPollerRuntime
from app.connectors.store import SqliteConnectorStore
from app.projects.models import Project, ProjectStatus
from app.projects.storage import SqliteProjectStore
from app.watcher.models import SignalType, TelemetryEvent
from app.watcher.service import WatcherService


@pytest.fixture
def test_db_path(tmp_path: Path) -> str:
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


@pytest.fixture
def mock_watcher() -> WatcherService:
    watcher = MagicMock(spec=WatcherService)
    watcher.ingest_event = AsyncMock()
    return watcher


def _create_project(project_store: SqliteProjectStore, project_id: str = "proj-poller") -> None:
    now = datetime.now(timezone.utc)
    proj = Project(
        project_id=project_id,
        name="Poller Project",
        workspace_path=f"D:/sample/{project_id}",
        normalized_path=f"d:/sample/{project_id}",
        is_git=False,
        status=ProjectStatus.READY,
        created_at=now,
        updated_at=now,
    )
    project_store.create_project(proj)


@pytest.mark.asyncio
async def test_target_failure_emits_telemetry_without_operational_degradation(
    project_store: SqliteProjectStore,
    connector_store: SqliteConnectorStore,
    mock_watcher: WatcherService,
) -> None:
    _create_project(project_store, "proj-poller")
    now = datetime.now(timezone.utc)

    connector = Connector(
        connector_id="conn-poll-target-fail",
        project_id="proj-poller",
        name="Target Failure Poller",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(
            url="http://127.0.0.1:54321/health",
            poll_interval_seconds=10,
            emit_health_telemetry=True,
        ),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(connector)

    runtime = ConnectorPollerRuntime(store=connector_store, watcher_service=mock_watcher)

    # Mock HTTP response with 503 Service Unavailable
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 503
    mock_response.text = "Service Unavailable"

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response

        result = await runtime.execute_single_poll(connector)
        assert result["status"] == "target_failure"
        assert result["status_code"] == 503

    # Check health invariants:
    health = connector_store.get_health("conn-poll-target-fail")
    assert health is not None
    assert health.target_status == TargetStatus.UNHEALTHY
    assert "503" in (health.last_target_error or "")
    # Invariant: Operational errors must NOT increment!
    assert health.consecutive_operational_errors == 0
    assert health.operational_status == OperationalStatus.HEALTHY
    assert health.last_operational_error is None

    # Telemetry Invariant: Must emit HEALTH event with ERROR level
    assert mock_watcher.ingest_event.call_count == 1
    event = mock_watcher.ingest_event.call_args[0][0]
    assert isinstance(event, TelemetryEvent)
    assert event.signal_type == SignalType.HEALTH
    assert event.level == "ERROR"
    assert event.project_id == "proj-poller"


@pytest.mark.asyncio
async def test_target_network_error_emits_telemetry_without_operational_degradation(
    project_store: SqliteProjectStore,
    connector_store: SqliteConnectorStore,
    mock_watcher: WatcherService,
) -> None:
    _create_project(project_store, "proj-poller")
    now = datetime.now(timezone.utc)

    connector = Connector(
        connector_id="conn-poll-net-err",
        project_id="proj-poller",
        name="Net Error Poller",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(
            url="http://127.0.0.1:54321/health",
            emit_health_telemetry=True,
        ),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(connector)

    runtime = ConnectorPollerRuntime(store=connector_store, watcher_service=mock_watcher)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = httpx.ConnectError("Connection refused")

        result = await runtime.execute_single_poll(connector)
        assert result["status"] == "target_failure"

    health = connector_store.get_health("conn-poll-net-err")
    assert health.target_status == TargetStatus.UNHEALTHY
    assert "Connection refused" in (health.last_target_error or "")
    assert health.consecutive_operational_errors == 0
    assert health.operational_status == OperationalStatus.HEALTHY

    assert mock_watcher.ingest_event.call_count == 1
    event = mock_watcher.ingest_event.call_args[0][0]
    assert event.level == "ERROR"


@pytest.mark.asyncio
async def test_operational_failure_degrades_connector_without_fake_telemetry(
    project_store: SqliteProjectStore,
    connector_store: SqliteConnectorStore,
    mock_watcher: WatcherService,
) -> None:
    _create_project(project_store, "proj-poller")
    now = datetime.now(timezone.utc)

    connector = Connector(
        connector_id="conn-poll-op-err",
        project_id="proj-poller",
        name="Op Error Poller",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(url="http://127.0.0.1:8080/health"),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(connector)

    runtime = ConnectorPollerRuntime(store=connector_store, watcher_service=mock_watcher)

    # Simulate an internal unexpected code exception during request
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = TypeError("Unexpected internal NoneType subscript")

        result = await runtime.execute_single_poll(connector)
        assert result["status"] == "operational_error"

    health = connector_store.get_health("conn-poll-op-err")
    assert health.operational_status == OperationalStatus.ERRORED
    assert health.consecutive_operational_errors == 1
    assert "Unexpected internal NoneType" in (health.last_operational_error or "")
    # Invariant: No fake target telemetry emitted!
    assert mock_watcher.ingest_event.call_count == 0


@pytest.mark.asyncio
async def test_successful_recovery_resets_operational_error_state(
    project_store: SqliteProjectStore,
    connector_store: SqliteConnectorStore,
    mock_watcher: WatcherService,
) -> None:
    _create_project(project_store, "proj-poller")
    now = datetime.now(timezone.utc)

    connector = Connector(
        connector_id="conn-poll-recover",
        project_id="proj-poller",
        name="Recovery Poller",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(url="http://127.0.0.1:8080/health"),
        status=ConnectorStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    connector_store.create_connector(connector)

    # Artificially set degraded health state
    health = connector_store.get_health("conn-poll-recover")
    health.operational_status = OperationalStatus.ERRORED
    health.consecutive_operational_errors = 4
    health.last_operational_error = "Prior crash"
    connector_store.update_health(health)

    runtime = ConnectorPollerRuntime(store=connector_store, watcher_service=mock_watcher)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.text = '{"status": "ok"}'

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp
        await runtime.execute_single_poll(connector)

    refreshed_health = connector_store.get_health("conn-poll-recover")
    assert refreshed_health.operational_status == OperationalStatus.HEALTHY
    assert refreshed_health.target_status == TargetStatus.HEALTHY
    assert refreshed_health.consecutive_operational_errors == 0
    assert refreshed_health.last_operational_error is None


@pytest.mark.asyncio
async def test_poller_restart_lifecycle(
    project_store: SqliteProjectStore,
    connector_store: SqliteConnectorStore,
    mock_watcher: WatcherService,
) -> None:
    _create_project(project_store, "proj-poller")
    now = datetime.now(timezone.utc)

    # 1. Enabled connector
    connector_store.create_connector(
        Connector(
            connector_id="conn-poll-enabled",
            project_id="proj-poller",
            name="Enabled Poller",
            connector_type=ConnectorType.HTTP_POLLER,
            config=ConnectorConfig(url="http://127.0.0.1:8080/health", poll_interval_seconds=10),
            status=ConnectorStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    )

    # 2. Disabled connector
    connector_store.create_connector(
        Connector(
            connector_id="conn-poll-disabled",
            project_id="proj-poller",
            name="Disabled Poller",
            connector_type=ConnectorType.HTTP_POLLER,
            config=ConnectorConfig(url="http://127.0.0.1:8080/health", poll_interval_seconds=10),
            status=ConnectorStatus.DISABLED,
            created_at=now,
            updated_at=now,
        )
    )

    # Simulate startup after restart
    runtime = ConnectorPollerRuntime(store=connector_store, watcher_service=mock_watcher)
    await runtime.start()

    # Invariant: Only enabled connector resumes background task
    assert "conn-poll-enabled" in runtime._tasks
    assert "conn-poll-disabled" not in runtime._tasks

    # Clean shutdown
    await runtime.stop()
    assert len(runtime._tasks) == 0

