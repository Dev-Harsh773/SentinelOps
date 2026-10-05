"""Service layer for Connector lifecycle management, authentication, deduplication, and ingestion."""

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

import httpx

from app.connectors.auth import WebhookAuthenticationError, verify_webhook_auth
from app.connectors.models import (
    Connector,
    ConnectorConfig,
    ConnectorCreateRequest,
    ConnectorHealth,
    ConnectorResponse,
    ConnectorStatus,
    ConnectorType,
    ConnectorUpdateRequest,
    OperationalStatus,
    TargetStatus,
    WebhookIngestRequest,
)
from app.connectors.normalizer import normalize_poller_result, normalize_webhook_payload
from app.connectors.redaction import is_secret_masked, mask_config_secrets, redact_secrets
from app.connectors.store import ConnectorNotFoundError, SqliteConnectorStore
from app.projects.storage import ProjectNotFoundError
from app.watcher.service import WatcherService

logger = logging.getLogger("sentinelops.connectors.service")


class ConnectorDisabledError(Exception):
    """Raised when an operation is attempted on a disabled connector."""

    def __init__(self, connector_id: str) -> None:
        super().__init__(f"Connector '{connector_id}' is disabled.")
        self.connector_id = connector_id


class InvalidConnectorOperationError(Exception):
    """Raised when an invalid operation is performed for a connector type."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ConnectorService:
    """Orchestrates connector CRUD, authentication, Option B deduplication, and telemetry ingestion."""

    def __init__(
        self,
        store: SqliteConnectorStore,
        watcher_service: WatcherService,
    ) -> None:
        self._store = store
        self._watcher_service = watcher_service
        self._connector_locks: Dict[str, asyncio.Lock] = {}
        self._locks_mutex = asyncio.Lock()
        self._runtime: Optional[Any] = None

    def set_runtime(self, runtime: Any) -> None:
        """Inject poller runtime for dynamic background task orchestration."""
        self._runtime = runtime

    async def _get_lock(self, connector_id: str) -> asyncio.Lock:
        """Get or create per-connector async lock for serialized ingestion."""
        async with self._locks_mutex:
            if connector_id not in self._connector_locks:
                self._connector_locks[connector_id] = asyncio.Lock()
            return self._connector_locks[connector_id]

    async def create_connector(self, request: ConnectorCreateRequest) -> ConnectorResponse:
        """Register a new connector, validating config and enforcing project ownership."""
        now = datetime.now(timezone.utc)
        connector_id = request.connector_id or f"conn-{uuid.uuid4().hex[:8]}"

        if request.connector_type == ConnectorType.HTTP_POLLER and not request.config.url:
            raise ValueError("URL is required for HTTP poller connectors")

        connector = Connector(
            connector_id=connector_id,
            project_id=request.project_id,
            name=request.name,
            connector_type=request.connector_type,
            config=request.config,
            status=request.status,
            created_at=now,
            updated_at=now,
        )

        created = self._store.create_connector(connector)
        health = self._store.get_health(connector_id)

        if self._runtime and connector.connector_type == ConnectorType.HTTP_POLLER and connector.status == ConnectorStatus.ACTIVE:
            try:
                await self._runtime.start_task(connector)
            except Exception as exc:
                logger.error("Failed to start runtime task for connector %s: %s; rolling back creation", connector_id, exc)
                try:
                    self._store.delete_connector(connector_id)
                except Exception as rb_exc:
                    logger.error("Compensating rollback failed for connector %s: %s", connector_id, rb_exc)
                raise

        return ConnectorResponse(
            connector_id=created.connector_id,
            project_id=created.project_id,
            name=created.name,
            connector_type=created.connector_type,
            config=mask_config_secrets(created.config),
            status=created.status,
            created_at=created.created_at,
            updated_at=created.updated_at,
            health=health,
        )

    def get_connector(self, connector_id: str) -> ConnectorResponse:
        """Retrieve a connector by ID with masked secrets."""
        connector = self._store.get_connector(connector_id)
        if not connector:
            raise ConnectorNotFoundError(connector_id)
        health = self._store.get_health(connector_id)
        return ConnectorResponse(
            connector_id=connector.connector_id,
            project_id=connector.project_id,
            name=connector.name,
            connector_type=connector.connector_type,
            config=mask_config_secrets(connector.config),
            status=connector.status,
            created_at=connector.created_at,
            updated_at=connector.updated_at,
            health=health,
        )

    def list_connectors(self, project_id: Optional[str] = None) -> List[ConnectorResponse]:
        """List connectors, optionally filtered by project_id, with masked secrets."""
        connectors = self._store.list_connectors(project_id=project_id)
        responses = []
        for c in connectors:
            health = self._store.get_health(c.connector_id)
            responses.append(
                ConnectorResponse(
                    connector_id=c.connector_id,
                    project_id=c.project_id,
                    name=c.name,
                    connector_type=c.connector_type,
                    config=mask_config_secrets(c.config),
                    status=c.status,
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                    health=health,
                )
            )
        return responses

    async def update_connector(self, connector_id: str, request: ConnectorUpdateRequest) -> ConnectorResponse:
        """Update an existing connector, preserving stored credentials if masked values are supplied."""
        existing = self._store.get_connector(connector_id)
        if not existing:
            raise ConnectorNotFoundError(connector_id)

        now = datetime.now(timezone.utc)
        new_name = request.name.strip() if request.name is not None and request.name.strip() else existing.name
        new_status = request.status if request.status is not None else existing.status

        if request.config is not None:
            updated_cfg_dict = request.config.model_dump()
            # Preserve auth_secret if masked or omitted
            if is_secret_masked(updated_cfg_dict.get("auth_secret")):
                updated_cfg_dict["auth_secret"] = existing.config.auth_secret
            elif updated_cfg_dict.get("auth_secret") is None:
                updated_cfg_dict["auth_secret"] = existing.config.auth_secret

            # Preserve masked header values
            existing_headers = existing.config.headers or {}
            new_headers = updated_cfg_dict.get("headers") or {}
            merged_headers = {}
            for hk, hv in new_headers.items():
                if is_secret_masked(hv) and hk in existing_headers:
                    merged_headers[hk] = existing_headers[hk]
                else:
                    merged_headers[hk] = hv
            updated_cfg_dict["headers"] = merged_headers

            new_config = ConnectorConfig.model_validate(updated_cfg_dict)
            if existing.connector_type == ConnectorType.HTTP_POLLER and not new_config.url:
                raise ValueError("URL cannot be removed from HTTP poller connector")
        else:
            new_config = existing.config

        updated_connector = Connector(
            connector_id=existing.connector_id,
            project_id=existing.project_id,
            name=new_name,
            connector_type=existing.connector_type,
            config=new_config,
            status=new_status,
            created_at=existing.created_at,
            updated_at=now,
        )

        persisted = self._store.update_connector(updated_connector)
        health = self._store.get_health(connector_id)

        # Update poller runtime if applicable
        if self._runtime and persisted.connector_type == ConnectorType.HTTP_POLLER:
            try:
                if persisted.status == ConnectorStatus.ACTIVE:
                    await self._runtime.start_task(persisted)
                else:
                    await self._runtime.stop_task(persisted.connector_id)
            except Exception as exc:
                logger.error("Failed to update runtime task for connector %s: %s; rolling back update", connector_id, exc)
                try:
                    self._store.update_connector(existing)
                    if existing.status == ConnectorStatus.ACTIVE:
                        await self._runtime.start_task(existing)
                    else:
                        await self._runtime.stop_task(existing.connector_id)
                except Exception as rb_exc:
                    logger.error("Compensating rollback failed for connector %s update: %s", connector_id, rb_exc)
                raise

        return ConnectorResponse(
            connector_id=persisted.connector_id,
            project_id=persisted.project_id,
            name=persisted.name,
            connector_type=persisted.connector_type,
            config=mask_config_secrets(persisted.config),
            status=persisted.status,
            created_at=persisted.created_at,
            updated_at=persisted.updated_at,
            health=health,
        )

    async def delete_connector(self, connector_id: str) -> bool:
        """Delete connector and tear down active background tasks."""
        if self._runtime:
            await self._runtime.stop_task(connector_id)

        deleted = self._store.delete_connector(connector_id)
        if not deleted:
            raise ConnectorNotFoundError(connector_id)
        return deleted

    async def ingest_webhook(
        self,
        connector_id: str,
        raw_body: bytes,
        headers: Dict[str, str],
        payload: WebhookIngestRequest,
    ) -> Dict[str, Any]:
        """Ingest webhook telemetry following Option B deduplication and strict status semantics.

        Deterministic Status:
        - Unknown connector: 404 (ConnectorNotFoundError)
        - Inactive/disabled: 409 (ConnectorDisabledError)
        - Wrong connector type: 400 (InvalidConnectorOperationError)
        - Bad authentication: 401 (WebhookAuthenticationError)
        """
        connector = self._store.get_connector(connector_id)
        if not connector:
            raise ConnectorNotFoundError(connector_id)

        if connector.status != ConnectorStatus.ACTIVE:
            raise ConnectorDisabledError(connector_id)

        if connector.connector_type != ConnectorType.WEBHOOK:
            raise InvalidConnectorOperationError(
                f"Connector '{connector_id}' is of type '{connector.connector_type.value}'; webhook ingestion is unsupported."
            )

        # Authenticate request
        verify_webhook_auth(connector, raw_body, headers)

        # Serialize ingestion per connector
        lock = await self._get_lock(connector_id)
        async with lock:
            ext_id = payload.external_event_id

            # Deduplication pre-check
            if ext_id and self._store.has_dedup_record(connector_id, ext_id):
                logger.info("Duplicate webhook delivery suppressed: connector=%s, ext_id=%s", connector_id, ext_id)
                return {
                    "status": "duplicate_suppressed",
                    "connector_id": connector_id,
                    "external_event_id": ext_id,
                    "event_id": None,
                }

            # Normalize into canonical Stage 10 TelemetryEvent
            event = normalize_webhook_payload(connector, payload)

            # Ingest into WatcherService (evaluates detection rules and correlates incidents)
            await self._watcher_service.ingest_event(event)

            # Only after Watcher success, record in deduplication log
            if ext_id:
                self._store.record_dedup(connector_id, ext_id, datetime.now(timezone.utc))

            return {
                "status": "ingested",
                "connector_id": connector_id,
                "event_id": event.event_id,
                "external_event_id": ext_id,
            }

    async def collect_connector(self, connector_id: str) -> Dict[str, Any]:
        """Trigger an on-demand collection probe for an HTTP poller connector."""
        connector = self._store.get_connector(connector_id)
        if not connector:
            raise ConnectorNotFoundError(connector_id)

        if connector.connector_type != ConnectorType.HTTP_POLLER:
            raise InvalidConnectorOperationError(
                f"Connector '{connector_id}' is a webhook connector; on-demand collect is unsupported."
            )

        if not self._runtime:
            raise RuntimeError("Poller runtime is not available")

        return await self._runtime.execute_single_poll(connector)

    async def test_connector(self, connector_id: str) -> Dict[str, Any]:
        """Perform a non-mutating connectivity test without altering connector health state."""
        connector = self._store.get_connector(connector_id)
        if not connector:
            raise ConnectorNotFoundError(connector_id)

        if connector.connector_type == ConnectorType.HTTP_POLLER:
            url = connector.config.url
            if not url:
                return {"status": "error", "message": "No URL configured"}

            from app.common.security import SSRFGuard, SSRFValidationError
            from app.connectors.redaction import scrub_string

            start = time.perf_counter()
            try:
                SSRFGuard.validate_url(url)
            except SSRFValidationError as exc:
                latency = (time.perf_counter() - start) * 1000.0
                return {
                    "status": "unreachable",
                    "error": f"SSRF security policy violation: {exc}",
                    "latency_ms": round(latency, 2),
                    "url": url,
                }

            try:
                async with httpx.AsyncClient(timeout=connector.config.timeout_seconds, follow_redirects=False) as client:
                    resp = await client.request(
                        method=connector.config.method,
                        url=url,
                        headers=connector.config.headers,
                    )
                    latency = (time.perf_counter() - start) * 1000.0
                    return {
                        "status": "success" if resp.status_code in connector.config.expected_status_codes else "degraded",
                        "status_code": resp.status_code,
                        "latency_ms": round(latency, 2),
                        "url": url,
                    }
            except Exception as exc:
                latency = (time.perf_counter() - start) * 1000.0
                return {
                    "status": "unreachable",
                    "error": scrub_string(str(exc)),
                    "latency_ms": round(latency, 2),
                    "url": url,
                }
        else:
            return {
                "status": "active" if connector.status == ConnectorStatus.ACTIVE else "disabled",
                "auth_configured": bool(connector.config.auth_secret),
                "connector_id": connector.connector_id,
            }
