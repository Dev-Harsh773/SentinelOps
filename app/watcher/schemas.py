"""Pydantic schemas for Sentinel Watcher API endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.watcher.models import CollectorHealth, CollectorStatus, CollectorType, SignalType, WatcherStatus


class TelemetryEventCreate(BaseModel):
    """Schema for external telemetry push ingestion.

    Explicitly requires project_id and service; does not permit silent default assignment.
    """

    project_id: str = Field(..., min_length=1, description="Explicit project identifier")
    service: str = Field(..., min_length=1, description="Explicit service name")
    signal_type: SignalType = Field(default=SignalType.LOG, description="Telemetry signal classification")
    event_type: str = Field(..., min_length=1, description="Specific event type")
    message: str = Field(..., min_length=1, description="Event message or log description")
    environment: Optional[str] = Field(default=None, description="Deployment environment")
    level: str = Field(default="INFO", description="Log or event level (INFO, WARNING, ERROR, etc.)")
    timestamp: Optional[datetime] = Field(default=None, description="Timestamp of event occurrence")
    request_id: Optional[str] = Field(default=None, description="Correlation request ID")
    trace_id: Optional[str] = Field(default=None, description="Distributed trace ID")
    endpoint: Optional[str] = Field(default=None, description="Target endpoint if applicable")
    status_code: Optional[int] = Field(default=None, description="HTTP status code if applicable")
    exception_type: Optional[str] = Field(default=None, description="Exception class name if applicable")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Structured contextual metadata")

    @field_validator("project_id", "service", "event_type", "message", mode="before")
    @classmethod
    def validate_non_empty_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("Field cannot be empty or blank")
            return stripped
        return v


class TelemetryEventBatchCreate(BaseModel):
    """Schema for batch telemetry push ingestion."""

    events: List[TelemetryEventCreate] = Field(..., min_length=1, description="List of events to ingest")


class TelemetryEventResponse(BaseModel):
    """API response model representing a TelemetryEvent."""

    event_id: str
    project_id: str
    service: str
    environment: str
    signal_type: SignalType
    source: str
    timestamp: datetime
    ingested_at: datetime
    level: str
    event_type: str
    message: str
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    endpoint: Optional[str] = None
    status_code: Optional[int] = None
    exception_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CollectorHealthResponse(BaseModel):
    """Diagnostic health summary of an individual collector."""

    name: str
    collector_type: CollectorType
    status: CollectorStatus
    last_event_at: Optional[datetime] = None
    total_events_collected: int
    error_count: int
    last_error: Optional[str] = None


class WatcherStatusResponse(BaseModel):
    """Operational health report for the Sentinel Watcher subsystem."""

    watcher_status: WatcherStatus
    enabled: bool
    uptime_seconds: float
    buffer: Dict[str, int]
    storage: Dict[str, Any]
    collectors: Dict[str, CollectorHealthResponse]


class IngestResponse(BaseModel):
    """Response returned upon accepting pushed telemetry."""

    status: str = "accepted"
    ingested_count: int
    event_ids: List[str]
