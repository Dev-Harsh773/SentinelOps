"""Pydantic request and response schemas for Incident API."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.incidents.models import IncidentStatus, Severity


class IncidentCreateRequest(BaseModel):
    """Payload for creating a new incident."""

    title: str = Field(..., max_length=200, description="Short summary of the incident")
    summary: str = Field(..., description="Detailed description of symptoms and observations")
    severity: Severity = Field(..., description="Severity level: low, medium, high, critical")
    service: str = Field(..., max_length=100, description="Affected service or component")
    environment: str = Field(..., max_length=100, description="Runtime environment e.g. production, staging")

    @field_validator("title", "summary", "service", "environment", mode="after")
    @classmethod
    def validate_non_empty_trimmed(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return trimmed


class IncidentStatusUpdateRequest(BaseModel):
    """Payload for updating an incident's lifecycle status."""

    status: IncidentStatus = Field(..., description="Target status: open, investigating, resolved, closed")


class IncidentResponse(BaseModel):
    """Standard representation of an incident returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    summary: str
    severity: Severity
    status: IncidentStatus
    service: str
    environment: str
    created_at: datetime
    updated_at: datetime
