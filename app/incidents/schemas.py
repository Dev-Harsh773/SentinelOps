"""Pydantic request and response schemas for Incident API."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.incidents.models import IncidentStatus, Severity


class IncidentCreateRequest(BaseModel):
    """Payload for creating a new incident."""

    title: str = Field(..., max_length=200, description="Short summary of the incident")
    summary: str = Field(..., description="Detailed description of symptoms and observations")
    severity: Severity = Field(..., description="Severity level: low, medium, high, critical")
    service: str = Field(..., max_length=100, description="Affected service or component")
    environment: str = Field(..., max_length=100, description="Runtime environment e.g. production, staging")
    project_id: Optional[str] = Field("default", description="Associated project identifier")

    @field_validator("title", "summary", "service", "environment", mode="after")
    @classmethod
    def validate_non_empty_trimmed(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return trimmed

    @field_validator("project_id", mode="before")
    @classmethod
    def normalize_project_id(cls, v: Optional[str]) -> str:
        if v is None:
            return "default"
        trimmed = v.strip()
        return trimmed if trimmed else "default"


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
    project_id: str = "default"
