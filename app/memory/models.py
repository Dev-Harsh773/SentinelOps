"""Incident memory and historical retrieval domain models and schemas."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# =====================================================================
# Domain Models (Internal Dataclasses)
# =====================================================================


@dataclass
class IncidentMemory:
    """Historical incident record persisted upon validated investigation completion."""

    incident_id: str
    service: str
    environment: str
    title: str
    failure_location: str
    triggering_condition: str
    root_cause_hypothesis: str
    summary: str
    endpoint: Optional[str] = None
    exception_type: Optional[str] = None
    relevant_symbols: List[str] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    resolution_notes: Optional[str] = None
    investigation_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HistoricalSearchQuery:
    """Query object for retrieving relevant historical incident context."""

    current_incident_id: str
    service: str
    environment: Optional[str] = None
    exception_type: Optional[str] = None
    endpoint: Optional[str] = None
    query_text: str = ""
    relevant_symbols: List[str] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    limit: int = 2


@dataclass
class HistoricalIncidentContext:
    """Context item representing a matched historical incident for advisory reasoning."""

    incident_id: str
    title: str
    service: str
    failure_location: str
    triggering_condition: str
    root_cause_hypothesis: str
    similarity_score: float
    matched_signals: List[str] = field(default_factory=list)
    resolution_notes: Optional[str] = None


# =====================================================================
# API Schemas (Pydantic Serialization)
# =====================================================================


class HistoricalIncidentContextSchema(BaseModel):
    """Schema for historical context presented in investigation results."""

    incident_id: str = Field(description="Historical incident ID")
    title: str = Field(description="Incident title")
    service: str = Field(description="Service name")
    failure_location: str = Field(description="Observed failure location from historical RCA")
    triggering_condition: str = Field(description="Triggering condition from historical RCA")
    root_cause_hypothesis: str = Field(description="Root cause hypothesis from historical RCA")
    similarity_score: float = Field(description="Calculated retrieval similarity score")
    matched_signals: List[str] = Field(default_factory=list, description="Categorical and lexical signals matched")
    resolution_notes: Optional[str] = Field(default=None, description="Optional resolution or mitigation notes")


class IncidentMemoryResponseSchema(BaseModel):
    """Schema for stored incident memory representation in API responses."""

    incident_id: str
    service: str
    environment: str
    title: str
    failure_location: str
    triggering_condition: str
    root_cause_hypothesis: str
    summary: str
    endpoint: Optional[str] = None
    exception_type: Optional[str] = None
    relevant_symbols: List[str] = Field(default_factory=list)
    relevant_files: List[str] = Field(default_factory=list)
    resolution_notes: Optional[str] = None
    investigation_id: str
    created_at: datetime
    updated_at: datetime


class MemorySearchRequestSchema(BaseModel):
    """Schema for searching historical incident memory via API."""

    current_incident_id: str = Field(description="Current incident ID to exclude from search results")
    service: str = Field(description="Service name to match")
    environment: Optional[str] = Field(default=None, description="Environment filter or context")
    exception_type: Optional[str] = Field(default=None, description="Observed exception class or type")
    endpoint: Optional[str] = Field(default=None, description="Observed HTTP endpoint")
    query_text: Optional[str] = Field(default="", description="Lexical search query text")
    relevant_symbols: List[str] = Field(default_factory=list, description="Relevant code symbols")
    relevant_files: List[str] = Field(default_factory=list, description="Relevant code files")
    limit: int = Field(default=2, ge=1, le=10, description="Maximum number of historical results to return")


class MemorySearchResponseSchema(BaseModel):
    """Schema for memory search response."""

    results: List[HistoricalIncidentContextSchema] = Field(default_factory=list)
    total: int = Field(description="Total number of matched results")
