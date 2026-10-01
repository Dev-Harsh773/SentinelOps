"""Project domain models for SentinelOps workspace onboarding."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class ProjectStatus(str, Enum):
    """Lifecycle state of an onboarded project."""

    REGISTERED = "registered"
    READY = "ready"
    ERROR = "error"


@dataclass
class Project:
    """Core domain model representing an onboarded repository workspace."""

    project_id: str
    name: str
    workspace_path: str
    normalized_path: str
    is_git: bool
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    description: Optional[str] = None
    default_branch: Optional[str] = None
    last_indexed_at: Optional[datetime] = None
    index_version: Optional[str] = None
    error_message: Optional[str] = None
    last_index_error: Optional[str] = None
