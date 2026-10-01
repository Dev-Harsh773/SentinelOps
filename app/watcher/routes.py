"""FastAPI HTTP routes for Sentinel Watcher telemetry ingestion and monitoring."""

from datetime import datetime, timezone
from typing import List, Optional, Union
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.common.config import config
from app.watcher.dependencies import get_watcher_service
from app.watcher.models import SignalType, TelemetryEvent
from app.watcher.schemas import (
    IngestResponse,
    TelemetryEventBatchCreate,
    TelemetryEventCreate,
    TelemetryEventResponse,
    WatcherStatusResponse,
)
from app.watcher.service import WatcherService

router = APIRouter(prefix="/watcher", tags=["Sentinel Watcher"])


@router.post(
    "/events",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest external runtime telemetry events",
)
async def ingest_telemetry_events(
    payload: Union[TelemetryEventBatchCreate, TelemetryEventCreate, List[TelemetryEventCreate]],
    service: WatcherService = Depends(get_watcher_service),
) -> IngestResponse:
    """Ingest one or more externally pushed telemetry events.

    Strictly requires explicit project_id and service for each event.
    Normalizes payloads into canonical TelemetryEvents and pushes to
    the rolling in-memory buffer and local persistence store.
    """
    now = datetime.now(timezone.utc)
    items: List[TelemetryEventCreate] = []

    if isinstance(payload, TelemetryEventBatchCreate):
        items = payload.events
    elif isinstance(payload, list):
        items = payload
    else:
        items = [payload]

    normalized_events: List[TelemetryEvent] = []
    event_ids: List[str] = []

    for item in items:
        event_id = str(uuid.uuid4())
        event_time = item.timestamp or now
        env = item.environment or config.watcher_default_environment

        event = TelemetryEvent(
            event_id=event_id,
            project_id=item.project_id,
            service=item.service,
            environment=env,
            signal_type=item.signal_type,
            source="http_api",
            timestamp=event_time,
            ingested_at=now,
            level=item.level.upper(),
            event_type=item.event_type,
            message=item.message,
            request_id=item.request_id,
            trace_id=item.trace_id,
            endpoint=item.endpoint,
            status_code=item.status_code,
            exception_type=item.exception_type,
            metadata=item.metadata,
        )
        normalized_events.append(event)
        event_ids.append(event_id)

    if len(normalized_events) == 1:
        await service.ingest_event(normalized_events[0])
    else:
        await service.ingest_batch(normalized_events)

    return IngestResponse(
        status="accepted",
        ingested_count=len(normalized_events),
        event_ids=event_ids,
    )


@router.get(
    "/status",
    response_model=WatcherStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Sentinel Watcher operational health and collector metrics",
)
def get_watcher_status(
    service: WatcherService = Depends(get_watcher_service),
) -> WatcherStatusResponse:
    """Return runtime diagnostic status, buffer usage, and individual collector health metrics."""
    return service.get_status()


@router.get(
    "/events",
    response_model=List[TelemetryEventResponse],
    status_code=status.HTTP_200_OK,
    summary="Query recent telemetry events from rolling buffer",
)
def get_recent_events(
    limit: int = Query(50, ge=1, le=1000, description="Maximum number of events to return"),
    signal_type: Optional[SignalType] = Query(None, description="Filter by signal category"),
    level: Optional[str] = Query(None, description="Filter by event level"),
    service_name: Optional[str] = Query(None, alias="service", description="Filter by service name"),
    project_id: Optional[str] = Query(None, description="Filter by project identifier"),
    service: WatcherService = Depends(get_watcher_service),
) -> List[TelemetryEventResponse]:
    """Retrieve recent buffered telemetry events in reverse chronological order."""
    events = service.get_events(
        limit=limit,
        signal_type=signal_type,
        level=level,
        service=service_name,
        project_id=project_id,
    )
    return [
        TelemetryEventResponse(
            event_id=e.event_id,
            project_id=e.project_id,
            service=e.service,
            environment=e.environment,
            signal_type=e.signal_type,
            source=e.source,
            timestamp=e.timestamp,
            ingested_at=e.ingested_at,
            level=e.level,
            event_type=e.event_type,
            message=e.message,
            request_id=e.request_id,
            trace_id=e.trace_id,
            endpoint=e.endpoint,
            status_code=e.status_code,
            exception_type=e.exception_type,
            metadata=e.metadata,
        )
        for e in events
    ]
