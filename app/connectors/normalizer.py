"""Normalizer converting external webhook and poller events to canonical TelemetryEvent."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from app.connectors.models import Connector, WebhookIngestRequest
from app.connectors.redaction import redact_secrets
from app.watcher.models import SignalType, TelemetryEvent


def _parse_signal_type(raw_type: Optional[str]) -> SignalType:
    """Parse string to SignalType enum safely, defaulting to CUSTOM or DEPLOYMENT."""
    if not raw_type:
        return SignalType.CUSTOM
    clean = raw_type.strip().lower()
    for sig in SignalType:
        if sig.value == clean:
            return sig
    return SignalType.CUSTOM


def normalize_webhook_payload(
    connector: Connector,
    request: WebhookIngestRequest,
) -> TelemetryEvent:
    """Normalize a validated webhook request into a canonical Stage 10 TelemetryEvent.

    Strict Invariant: event.project_id is ALWAYS connector.project_id,
    overriding any client-supplied payload property.
    """
    now = datetime.now(timezone.utc)
    event_id = f"evt-{uuid.uuid4().hex[:12]}"

    signal_type = _parse_signal_type(request.signal_type) if request.signal_type else SignalType.DEPLOYMENT
    level = (request.level or "INFO").upper()

    metadata = dict(request.metadata or {})
    if request.payload:
        metadata["payload"] = request.payload
    metadata["connector_id"] = connector.connector_id
    metadata["connector_type"] = connector.connector_type.value
    if request.external_event_id:
        metadata["external_event_id"] = request.external_event_id

    # Redact sensitive secrets from metadata
    clean_metadata = redact_secrets(metadata)

    return TelemetryEvent(
        event_id=event_id,
        project_id=connector.project_id,
        service=request.service or connector.config.service or "webhook-service",
        environment=request.environment or connector.config.environment or "production",
        signal_type=signal_type,
        source=f"connector:{connector.connector_id}",
        timestamp=request.timestamp or now,
        ingested_at=now,
        level=level,
        event_type=request.event_type or "webhook.event",
        message=redact_secrets(request.message or "Webhook event received"),
        request_id=request.external_event_id,
        trace_id=None,
        endpoint=request.endpoint,
        status_code=request.status_code,
        exception_type=request.exception_type,
        metadata=clean_metadata,
    )


def normalize_poller_result(
    connector: Connector,
    status_code: Optional[int],
    response_text: Optional[str],
    latency_ms: float,
    is_error: bool = False,
    error_message: Optional[str] = None,
) -> TelemetryEvent:
    """Normalize an HTTP poller health check probe into a canonical Stage 10 TelemetryEvent."""
    now = datetime.now(timezone.utc)
    event_id = f"evt-{uuid.uuid4().hex[:12]}"

    level = "ERROR" if is_error else "INFO"
    event_type = "health.check.failure" if is_error else "health.check.success"
    message = error_message or f"HTTP Poller probe returned status {status_code}"

    meta = {
        "connector_id": connector.connector_id,
        "url": connector.config.url,
        "latency_ms": round(latency_ms, 2),
    }
    if response_text:
        meta["response_snippet"] = response_text[:500]

    return TelemetryEvent(
        event_id=event_id,
        project_id=connector.project_id,
        service=connector.config.service,
        environment=connector.config.environment or "production",
        signal_type=SignalType.HEALTH,
        source=f"connector:{connector.connector_id}",
        timestamp=now,
        ingested_at=now,
        level=level,
        event_type=event_type,
        message=message,
        request_id=None,
        trace_id=None,
        endpoint=connector.config.url,
        status_code=status_code,
        exception_type="TargetHealthFailure" if is_error else None,
        metadata=redact_secrets(meta),
    )
