"""Pydantic schemas for SentinelOps telemetry and evidence collection endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.telemetry.models import EvidenceType


class EvidenceCollectRequest(BaseModel):
    """Payload to trigger manual evidence collection for an incident."""

    request_id: str = Field(..., description="Target request ID to locate in runtime logs")

    @field_validator("request_id", mode="after")
    @classmethod
    def validate_request_id(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("request_id cannot be empty or whitespace only.")
        return trimmed


class EvidenceResponse(BaseModel):
    """Representation of an individual evidence record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_id: str
    type: EvidenceType
    source: str
    timestamp: datetime
    service: str
    request_id: str
    level: str
    event: str
    message: str
    endpoint: Optional[str] = None
    exception_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class EvidenceCollectionResponse(BaseModel):
    """Result of an evidence collection attempt."""

    incident_id: str
    request_id: str
    collected: int = Field(..., description="Number of newly created Evidence records during this request")
    evidence: List[EvidenceResponse] = Field(default_factory=list, description="Newly attached evidence records")
    message: str = Field(..., description="Human-readable status summary")
