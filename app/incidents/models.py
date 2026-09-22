"""Incident domain models and enumerated types."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    """Incident severity classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    """Incident lifecycle state."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


@dataclass
class Incident:
    """Core domain model representing a runtime application incident."""

    id: str
    title: str
    summary: str
    severity: Severity
    status: IncidentStatus
    service: str
    environment: str
    created_at: datetime
    updated_at: datetime
