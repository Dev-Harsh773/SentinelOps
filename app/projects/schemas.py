"""Pydantic request and response schemas for Project onboarding API."""

from datetime import datetime
import re
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.projects.models import ProjectStatus

PROJECT_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class ProjectRegisterRequest(BaseModel):
    """Payload for onboarding a new project."""

    name: str = Field(..., max_length=128, description="Display name for project")
    workspace_path: str = Field(..., description="Filesystem directory path to project workspace")
    project_id: Optional[str] = Field(None, max_length=64, description="Optional custom project identifier")
    description: Optional[str] = Field(None, max_length=500, description="Optional project description")

    @field_validator("project_id", mode="after")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            return None
        if not PROJECT_ID_REGEX.match(trimmed):
            raise ValueError(
                "project_id must contain only alphanumeric characters, dashes, underscores, and dots."
            )
        return trimmed

    @field_validator("name", "workspace_path", mode="after")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return trimmed


class GitHubProjectRegisterRequest(BaseModel):
    """Payload for atomically onboarding a public GitHub repository."""

    name: str = Field(..., max_length=128, description="Display name for project")
    repo_url: str = Field(..., description="HTTPS GitHub repository URL")
    project_id: Optional[str] = Field(None, max_length=64, description="Optional custom project identifier")
    branch: Optional[str] = Field(None, max_length=128, description="Optional Git branch to checkout")
    description: Optional[str] = Field(None, max_length=500, description="Optional project description")

    @field_validator("project_id", mode="after")
    @classmethod
    def validate_project_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            return None
        if not PROJECT_ID_REGEX.match(trimmed):
            raise ValueError(
                "project_id must contain only alphanumeric characters, dashes, underscores, and dots."
            )
        return trimmed

    @field_validator("name", "repo_url", mode="after")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or contain only whitespace.")
        return trimmed


class ProjectReadinessResponse(BaseModel):
    """Current operational readiness and connection status for a project."""

    project_id: str
    project_status: ProjectStatus
    is_indexed: bool
    source_connected: bool
    connectors_count: int
    active_connectors_count: int
    health_status: Optional[str] = None
    last_telemetry_at: Optional[datetime] = None
    telemetry_receiving: bool
    recency_window_seconds: int
    external_webhook_ready: bool



class ProjectResponse(BaseModel):
    """API representation of an onboarded project."""

    model_config = ConfigDict(from_attributes=True)

    project_id: str
    name: str
    description: Optional[str]
    workspace_path: str
    is_git: bool
    default_branch: Optional[str]
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    last_indexed_at: Optional[datetime]
    index_version: Optional[str]
    error_message: Optional[str]
    last_index_error: Optional[str]
