"""Tests for ConnectorService, Option B deduplication, secret redaction, and auth."""

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.connectors.auth import WebhookAuthenticationError
from app.connectors.models import (
    ConnectorConfig,
    ConnectorCreateRequest,
    ConnectorStatus,
    ConnectorType,
    ConnectorUpdateRequest,
    WebhookIngestRequest,
)
from app.connectors.redaction import is_secret_masked, mask_secret, redact_secrets
from app.connectors.service import (
    ConnectorDisabledError,
    ConnectorService,
    InvalidConnectorOperationError,
)
from app.connectors.store import ConnectorNotFoundError, SqliteConnectorStore
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


@pytest.fixture
def connector_service(connector_store: SqliteConnectorStore, mock_watcher: WatcherService) -> ConnectorService:
    return ConnectorService(store=connector_store, watcher_service=mock_watcher)


def _init_project(project_store: SqliteProjectStore, project_id: str = "proj-service") -> None:
    now = datetime.now(timezone.utc)
    proj = Project(
        project_id=project_id,
        name="Service Test Project",
        workspace_path=f"D:/sample/{project_id}",
        normalized_path=f"d:/sample/{project_id}",
        is_git=False,
        status=ProjectStatus.READY,
        created_at=now,
        updated_at=now,
    )
    project_store.create_project(proj)


@pytest.mark.asyncio
async def test_option_b_deduplication_flow(
    project_store: SqliteProjectStore,
    connector_service: ConnectorService,
    mock_watcher: WatcherService,
) -> None:
    _init_project(project_store, "proj-service")

    # 1. Create webhook connector
    created = await connector_service.create_connector(
        ConnectorCreateRequest(
            connector_id="conn-wh-1",
            project_id="proj-service",
            name="Dedup Webhook",
            connector_type=ConnectorType.WEBHOOK,
            config=ConnectorConfig(),
        )
    )
    assert created.connector_id == "conn-wh-1"

    payload = WebhookIngestRequest(
        external_event_id="ext-evt-999",
        message="Build finished",
        service="ci-builder",
    )

    # 2. First delivery: must ingest into Watcher and commit dedup record
    res1 = await connector_service.ingest_webhook(
        connector_id="conn-wh-1",
        raw_body=b'{"external_event_id": "ext-evt-999"}',
        headers={},
        payload=payload,
    )
    assert res1["status"] == "ingested"
    assert res1["external_event_id"] == "ext-evt-999"
    assert mock_watcher.ingest_event.call_count == 1

    # Verify event passed to Watcher has connector's project_id
    call_args = mock_watcher.ingest_event.call_args[0][0]
    assert isinstance(call_args, TelemetryEvent)
    assert call_args.project_id == "proj-service"
    assert call_args.service == "ci-builder"

    # 3. Second delivery with same external_event_id: must be suppressed before Watcher
    res2 = await connector_service.ingest_webhook(
        connector_id="conn-wh-1",
        raw_body=b'{"external_event_id": "ext-evt-999"}',
        headers={},
        payload=payload,
    )
    assert res2["status"] == "duplicate_suppressed"
    assert res2["external_event_id"] == "ext-evt-999"
    # Call count should still be 1 (no second call)
    assert mock_watcher.ingest_event.call_count == 1


@pytest.mark.asyncio
async def test_option_b_watcher_failure_does_not_persist_dedup(
    project_store: SqliteProjectStore,
    connector_service: ConnectorService,
    connector_store: SqliteConnectorStore,
    mock_watcher: WatcherService,
) -> None:
    _init_project(project_store, "proj-service")

    await connector_service.create_connector(
        ConnectorCreateRequest(
            connector_id="conn-crash",
            project_id="proj-service",
            name="Crash Webhook",
            connector_type=ConnectorType.WEBHOOK,
            config=ConnectorConfig(),
        )
    )

    # Simulate Watcher ingestion exception
    mock_watcher.ingest_event.side_effect = RuntimeError("Watcher buffer memory full")

    payload = WebhookIngestRequest(
        external_event_id="ext-fail-1",
        message="Event before crash",
    )

    # Ingestion fails
    with pytest.raises(RuntimeError, match="Watcher buffer memory full"):
        await connector_service.ingest_webhook(
            connector_id="conn-crash",
            raw_body=b'{}',
            headers={},
            payload=payload,
        )

    # Invariant: No dedup record saved!
    assert connector_store.has_dedup_record("conn-crash", "ext-fail-1") is False

    # Simulate recovery: Watcher now succeeds
    mock_watcher.ingest_event.side_effect = None
    res = await connector_service.ingest_webhook(
        connector_id="conn-crash",
        raw_body=b'{}',
        headers={},
        payload=payload,
    )
    assert res["status"] == "ingested"
    assert connector_store.has_dedup_record("conn-crash", "ext-fail-1") is True


@pytest.mark.asyncio
async def test_no_external_id_has_at_least_once_behavior(
    project_store: SqliteProjectStore,
    connector_service: ConnectorService,
    mock_watcher: WatcherService,
) -> None:
    _init_project(project_store, "proj-service")

    await connector_service.create_connector(
        ConnectorCreateRequest(
            connector_id="conn-no-ext-id",
            project_id="proj-service",
            name="No ID Webhook",
            connector_type=ConnectorType.WEBHOOK,
            config=ConnectorConfig(),
        )
    )

    payload = WebhookIngestRequest(external_event_id=None, message="Anonymous event")

    # Ingest twice without external_event_id: both must succeed
    res1 = await connector_service.ingest_webhook(
        connector_id="conn-no-ext-id", raw_body=b'{}', headers={}, payload=payload
    )
    res2 = await connector_service.ingest_webhook(
        connector_id="conn-no-ext-id", raw_body=b'{}', headers={}, payload=payload
    )
    assert res1["status"] == "ingested"
    assert res2["status"] == "ingested"
    assert mock_watcher.ingest_event.call_count == 2


@pytest.mark.asyncio
async def test_webhook_authentication_and_health_integrity(
    project_store: SqliteProjectStore,
    connector_service: ConnectorService,
    connector_store: SqliteConnectorStore,
) -> None:
    _init_project(project_store, "proj-service")

    secret = "my-shared-hmac-secret"
    await connector_service.create_connector(
        ConnectorCreateRequest(
            connector_id="conn-auth",
            project_id="proj-service",
            name="Auth Webhook",
            connector_type=ConnectorType.WEBHOOK,
            config=ConnectorConfig(
                auth_secret=secret,
                signature_header="X-Hub-Signature-256",
            ),
        )
    )

    raw_body = b'{"hello": "world"}'
    valid_sig = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    invalid_sig = "sha256=badbadbadbad00000000000000000000"

    payload = WebhookIngestRequest(message="Test Auth")

    # 1. Invalid signature raises WebhookAuthenticationError
    with pytest.raises(WebhookAuthenticationError):
        await connector_service.ingest_webhook(
            connector_id="conn-auth",
            raw_body=raw_body,
            headers={"X-Hub-Signature-256": invalid_sig},
            payload=payload,
        )

    # Invariant: Bad auth must NOT degrade connector operational health!
    health = connector_store.get_health("conn-auth")
    assert health.operational_status == "healthy"
    assert health.consecutive_operational_errors == 0

    # 2. Valid signature succeeds
    res = await connector_service.ingest_webhook(
        connector_id="conn-auth",
        raw_body=raw_body,
        headers={"X-Hub-Signature-256": valid_sig},
        payload=payload,
    )
    assert res["status"] == "ingested"


@pytest.mark.asyncio
async def test_secret_redaction_and_masked_update_preservation(
    project_store: SqliteProjectStore,
    connector_service: ConnectorService,
    connector_store: SqliteConnectorStore,
) -> None:
    _init_project(project_store, "proj-service")

    original_secret = "sensitive-api-token-xyz-12345"

    # 1. Create with sensitive secret
    created = await connector_service.create_connector(
        ConnectorCreateRequest(
            connector_id="conn-redact",
            project_id="proj-service",
            name="Redact Connector",
            connector_type=ConnectorType.WEBHOOK,
            config=ConnectorConfig(auth_secret=original_secret),
        )
    )
    # API response must mask secret
    assert is_secret_masked(created.config.auth_secret)
    assert created.config.auth_secret != original_secret

    # Storage must retain actual plaintext secret for runtime auth
    stored = connector_store.get_connector("conn-redact")
    assert stored.config.auth_secret == original_secret

    # 2. Update with masked secret in request: must preserve original stored secret
    updated = await connector_service.update_connector(
        "conn-redact",
        ConnectorUpdateRequest(
            name="Renamed Redact",
            config=ConnectorConfig(auth_secret=created.config.auth_secret),
        ),
    )
    assert updated.name == "Renamed Redact"
    re_stored = connector_store.get_connector("conn-redact")
    assert re_stored.config.auth_secret == original_secret


def test_recursive_secret_redaction() -> None:
    nested = {
        "user": "alice",
        "api_key": "top-secret-key-val",
        "nested": {
            "password": "mypassword123",
            "token": "bearer-token-val",
            "notes": "Here is my token: ghp_123456789012345678901234567890123456 and more",
        },
        "items": [
            {"secret": "hidden-secret"},
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz",
        ],
    }

    redacted = redact_secrets(nested)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert "[REDACTED_GH_TOKEN]" in redacted["nested"]["notes"]
    assert redacted["items"][0]["secret"] == "[REDACTED]"
    assert "Bearer [REDACTED]" in redacted["items"][1]


@pytest.mark.asyncio
async def test_simulated_runtime_start_failure_during_create_leaves_no_connector_row(
    project_store: SqliteProjectStore,
    connector_service: ConnectorService,
    connector_store: SqliteConnectorStore,
) -> None:
    _init_project(project_store, "proj-service")

    mock_runtime = MagicMock()
    mock_runtime.start_task = AsyncMock(side_effect=RuntimeError("Simulated event loop crash"))
    connector_service.set_runtime(mock_runtime)

    req = ConnectorCreateRequest(
        connector_id="conn-fail-rollback",
        project_id="proj-service",
        name="Failing Poller",
        connector_type=ConnectorType.HTTP_POLLER,
        config=ConnectorConfig(url="http://127.0.0.1:8080/health"),
        status=ConnectorStatus.ACTIVE,
    )

    with pytest.raises(RuntimeError, match="Simulated event loop crash"):
        await connector_service.create_connector(req)

    # Invariant: Compensating rollback leaves NO zombie connector row
    assert connector_store.get_connector("conn-fail-rollback") is None
    assert connector_store.get_health("conn-fail-rollback") is None


@pytest.mark.asyncio
async def test_simulated_enable_restart_failure_reverts_stored_state(
    project_store: SqliteProjectStore,
    connector_service: ConnectorService,
    connector_store: SqliteConnectorStore,
) -> None:
    _init_project(project_store, "proj-service")

    mock_runtime = MagicMock()
    mock_runtime.start_task = AsyncMock()
    mock_runtime.stop_task = AsyncMock()
    connector_service.set_runtime(mock_runtime)

    # Create initially disabled connector
    await connector_service.create_connector(
        ConnectorCreateRequest(
            connector_id="conn-update-rollback",
            project_id="proj-service",
            name="Toggle Poller",
            connector_type=ConnectorType.HTTP_POLLER,
            config=ConnectorConfig(url="http://127.0.0.1:8080/health"),
            status=ConnectorStatus.DISABLED,
        )
    )

    # Set runtime to fail when enabling
    mock_runtime.start_task.side_effect = RuntimeError("Runtime activation failed")

    with pytest.raises(RuntimeError, match="Runtime activation failed"):
        await connector_service.update_connector(
            "conn-update-rollback",
            ConnectorUpdateRequest(status=ConnectorStatus.ACTIVE),
        )

    # Invariant: Stored status must remain reverted to DISABLED
    stored = connector_store.get_connector("conn-update-rollback")
    assert stored is not None
    assert stored.status == ConnectorStatus.DISABLED
