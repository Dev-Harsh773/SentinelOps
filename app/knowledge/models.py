"""Domain models for Project Knowledge Base snapshots and extracted artifacts."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class DetectedRoute:
    """Represents an HTTP endpoint detected via AST inspection."""

    method: str  # GET, POST, PUT, DELETE, etc.
    path: str  # e.g. /orders
    file_path: str  # Repo-relative POSIX path
    function_name: str  # Function or method handling the route
    start_line: int


@dataclass(frozen=True)
class ConfigFileInfo:
    """Represents a discovered top-level project configuration file."""

    file_name: str  # pyproject.toml, requirements.txt, config.py, etc.
    rel_path: str
    size_bytes: int


@dataclass
class ProjectKnowledgeSnapshot:
    """Consolidated knowledge snapshot of an onboarded project's codebase and Git state."""

    project_id: str
    index_version: str
    indexed_at: datetime
    files_count: int
    chunks_count: int
    routes: List[DetectedRoute] = field(default_factory=list)
    config_files: List[ConfigFileInfo] = field(default_factory=list)
    is_git: bool = False
    current_head: Optional[str] = None
    current_branch: Optional[str] = None
