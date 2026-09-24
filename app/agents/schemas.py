"""Pydantic schemas for serialization and structured output validation in SentinelOps investigations."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.memory.models import HistoricalIncidentContextSchema


class EvidenceReferenceSchema(BaseModel):
    """Schema for referencing concrete supporting or contradicting evidence."""

    type: str = Field(description="Evidence type: 'runtime', 'code', or 'git_commit'")
    id: str = Field(description="Stable evidence identifier (evidence UUID, chunk ID, or commit hash)")
    description: Optional[str] = Field(default=None, description="Optional brief description of what this evidence shows")


class RuntimeAnalysisSchema(BaseModel):
    """Schema for structured runtime symptom extraction."""

    observed_failures: List[str] = Field(default_factory=list, description="Observed error symptoms from logs")
    service: str = Field(default="", description="Name of the service that experienced the failure")
    endpoint: Optional[str] = Field(default=None, description="HTTP endpoint or route involved")
    exception_type: Optional[str] = Field(default=None, description="Exception class or error code")
    important_messages: List[str] = Field(default_factory=list, description="Key log messages or error messages")
    request_ids: List[str] = Field(default_factory=list, description="Correlation or request IDs involved")
    timeline: List[str] = Field(default_factory=list, description="Chronological sequence of observed runtime events")
    initial_hypotheses: List[str] = Field(default_factory=list, description="Early working hypotheses based on runtime facts")
    missing_information: List[str] = Field(default_factory=list, description="Information not observable from the runtime logs")


class CodeAnalysisSchema(BaseModel):
    """Schema for structured code analysis."""

    relevant_symbols: List[str] = Field(default_factory=list, description="Relevant functions, classes, or methods")
    relevant_files: List[str] = Field(default_factory=list, description="Relevant repository-relative source files")
    code_observations: List[str] = Field(default_factory=list, description="Factual observations from retrieved source code")
    possible_relationship_to_failure: List[str] = Field(default_factory=list, description="How the code relates to the observed failure")
    missing_code_context: List[str] = Field(default_factory=list, description="Source context that could not be determined")


class ChangeAnalysisSchema(BaseModel):
    """Schema for structured Git change analysis."""

    relevant_changes: List[str] = Field(default_factory=list, description="Recent commits or changes touching relevant files")
    potential_relationships: List[str] = Field(default_factory=list, description="Plausible connections between changes and failure")
    timing_observations: List[str] = Field(default_factory=list, description="Timeline relationship between commit dates and incident")
    contradictions: List[str] = Field(default_factory=list, description="Observations that contradict a commit being responsible")
    uncertainty: List[str] = Field(default_factory=list, description="Known uncertainties in change attribution")
    facts: List[str] = Field(default_factory=list, description="Factual statements about the Git history")
    inferences: List[str] = Field(default_factory=list, description="Inferences made about the changes, separated from facts")


class RootCauseAnalysisSchema(BaseModel):
    """Schema for synthesized Root Cause Analysis."""

    failure_location: str = Field(
        default="",
        description="Specific component, class, method, or subsystem where the error surfaced",
    )
    triggering_condition: str = Field(
        default="",
        description="The underlying condition, flag, state, or branch evaluated that caused the failure to execute",
    )
    root_cause_hypothesis: str = Field(description="Primary causal explanation of why the failure occurred")
    affected_component: str = Field(
        default="",
        description="Component affected (mirrors failure_location)",
    )
    summary: str = Field(description="High-level narrative summary of the incident and root cause")
    supporting_evidence: List[EvidenceReferenceSchema] = Field(
        default_factory=list,
        description="List of concrete evidence items directly supporting this root cause",
    )
    contradicting_evidence: List[EvidenceReferenceSchema] = Field(
        default_factory=list,
        description="Evidence that challenges or weakens this hypothesis",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model-assessed investigation confidence from 0.0 to 1.0 (not statistical probability)",
    )
    uncertainties: List[str] = Field(
        default_factory=list,
        description="Explicit uncertainties, unknowns, or unverified assumptions",
    )


class RCAValidationSchema(BaseModel):
    """Schema for validating RCA claims against evidence."""

    valid: bool = Field(description="True if the RCA is sufficiently grounded in evidence without hallucinations")
    issues: List[str] = Field(default_factory=list, description="Identified logical flaws, ungrounded claims, or errors")
    unsupported_claims: List[str] = Field(default_factory=list, description="Claims made in RCA lacking supporting evidence")
    missing_evidence: List[str] = Field(default_factory=list, description="Evidence required to substantiate ungrounded claims")


class CodeResultSummarySchema(BaseModel):
    """Summary of an indexed code chunk retrieved during investigation."""

    id: str
    file_path: str
    symbol_name: Optional[str] = None
    symbol_type: str
    start_line: int
    end_line: int
    score: float


class InvestigationResponse(BaseModel):
    """Full API response schema for an incident investigation."""

    investigation_id: str
    incident_id: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    runtime_analysis: Optional[RuntimeAnalysisSchema] = None
    code_query: Optional[str] = None
    code_results: List[Dict[str, Any]] = Field(default_factory=list)
    code_analysis: Optional[CodeAnalysisSchema] = None
    git_context: List[Dict[str, Any]] = Field(default_factory=list)
    change_analysis: Optional[ChangeAnalysisSchema] = None
    historical_context: List[HistoricalIncidentContextSchema] = Field(default_factory=list)
    rca: Optional[RootCauseAnalysisSchema] = None
    validation: Optional[RCAValidationSchema] = None
    errors: List[str] = Field(default_factory=list)
