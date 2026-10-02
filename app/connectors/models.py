"""Domain models and schemas for SentinelOps Deployment and Telemetry Connectors."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, field_validator


class ConnectorType(str, Enum):
    """Supported connector intake modes."""

    HTTP_POLLER = "http_poller"
    WEBHOOK = "webhook"


class ConnectorStatus(str, Enum):
    """Lifecycle status of a connector."""

    ACTIVE = "active"
    DISABLED = "disabled"


class OperationalStatus(str, Enum):
    """Internal runtime status of the connector mechanism itself."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ERRORED = "errored"


class TargetStatus(str, Enum):
    """Health status of the remote monitored service/target."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ConnectorConfig(BaseModel):
    """Configuration options for HTTP poller or Webhook intake."""

    # Common / Shared
    service: str = Field(default="monitored-service", description="Service identifier for emitted events")
    environment: Optional[str] = Field(default=None, description="Environment tag (e.g. production, staging)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata tags")

    # HTTP Poller specifics
    url: Optional[str] = Field(default=None, description="Target URL for HTTP poller")
    method: str = Field(default="GET", description="HTTP request method")
    headers: Dict[str, str] = Field(default_factory=dict, description="HTTP request headers")
    poll_interval_seconds: int = Field(default=60, ge=5, le=86400, description="Polling frequency")
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0, description="HTTP client timeout")
    expected_status_codes: List[int] = Field(default_factory=lambda: [200], description="Expected status codes")
    emit_health_telemetry: bool = Field(default=True, description="Whether to emit HEALTH telemetry events")

    # Webhook specifics
    auth_secret: Optional[str] = Field(default=None, description="Shared secret for HMAC or token auth")
    signature_header: Optional[str] = Field(default=None, description="Header containing HMAC signature")
    signature_algorithm: Optional[str] = Field(default="sha256", description="HMAC algorithm (e.g. sha256)")
    token_header: Optional[str] = Field(default=None, description="Header containing auth bearer/token")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not (clean.startswith("http://") or clean.startswith("https://")):
                raise ValueError("URL must start with http:// or https://")
            return clean
        return v


class Connector(BaseModel):
    """Durable connector record representing an external telemetry pipeline."""

    connector_id: str
    project_id: str
    name: str
    connector_type: ConnectorType
    config: ConnectorConfig
    status: ConnectorStatus = ConnectorStatus.ACTIVE
    created_at: datetime
    updated_at: datetime


class ConnectorHealth(BaseModel):
    """Diagnostic health status for a connector."""

    connector_id: str
    operational_status: OperationalStatus = OperationalStatus.HEALTHY
    target_status: TargetStatus = TargetStatus.UNKNOWN
    last_poll_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    consecutive_operational_errors: int = 0
    last_operational_error: Optional[str] = None
    last_target_error: Optional[str] = None


class ConnectorCreateRequest(BaseModel):
    """Request payload to onboard a connector."""

    connector_id: Optional[str] = None
    project_id: str
    name: str
    connector_type: ConnectorType
    config: ConnectorConfig
    status: ConnectorStatus = ConnectorStatus.ACTIVE

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Connector name cannot be blank")
        return clean


class ConnectorUpdateRequest(BaseModel):
    """Request payload to update a connector."""

    name: Optional[str] = None
    config: Optional[ConnectorConfig] = None
    status: Optional[ConnectorStatus] = None


class WebhookIngestRequest(BaseModel):
    """Flexible webhook ingestion payload mapping to canonical TelemetryEvent."""

    external_event_id: Optional[str] = None
    signal_type: Optional[str] = None
    level: Optional[str] = "INFO"
    event_type: Optional[str] = "webhook.event"
    message: Optional[str] = "Webhook telemetry received"
    service: Optional[str] = None
    environment: Optional[str] = None
    endpoint: Optional[str] = None
    status_code: Optional[int] = None
    exception_type: Optional[str] = None
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    payload: Optional[Dict[str, Any]] = None


class ConnectorResponse(BaseModel):
    """API view model for a connector with masked secrets."""

    connector_id: str
    project_id: str
    name: str
    connector_type: ConnectorType
    config: ConnectorConfig
    status: ConnectorStatus
    created_at: datetime
    updated_at: datetime
    health: Optional[ConnectorHealth] = None
