"""Pydantic request and response schemas for Project onboarding API."""

from datetime import datetime
import re
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.projects.models import ProjectStatus

PROJECT_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class ProjectRegisterRequest(BaseModel):
    """Payload for onboarding a new project."""

    project_id: str = Field(..., max_length=64, description="Unique, stable project identifier")
    name: str = Field(..., max_length=128, description="Display name for project")
    workspace_path: str = Field(..., description="Filesystem directory path to project workspace")
    description: Optional[str] = Field(None, max_length=500, description="Optional project description")

    @field_validator("project_id", mode="after")
    @classmethod
    def validate_project_id(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("project_id cannot be empty.")
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
