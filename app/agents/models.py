"""Investigation domain models and exceptions for SentinelOps."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# =====================================================================
# Domain Exceptions
# =====================================================================


class InvestigationNotFoundError(Exception):
    """Raised when an investigation cannot be found for an incident."""

    def __init__(self, incident_id: str):
        super().__init__(f"No investigation found for incident '{incident_id}'.")
        self.incident_id = incident_id


class NoEvidenceForInvestigationError(Exception):
    """Raised when an investigation is attempted on an incident with no attached runtime evidence."""

    def __init__(self, incident_id: str):
        super().__init__(f"Incident '{incident_id}' has no runtime evidence available for investigation.")
        self.incident_id = incident_id


class InvestigationLLMError(Exception):
    """Raised when an underlying LLM provider fails during investigation reasoning."""

    def __init__(self, message: str = "Investigation reasoning service encountered an error."):
        super().__init__(message)


# =====================================================================
# Structured Output & Evidence Models
# =====================================================================


class InvestigationStatus(str, Enum):
    """Status lifecycle for an incident investigation workflow."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class EvidenceReference:
    """Stable reference to concrete evidence supporting or contradicting an RCA claim."""

    type: str  # "runtime", "code", "git_commit"
    id: str  # stable ID: evidence UUID, deterministic chunk ID, or hex commit hash
    description: Optional[str] = None


@dataclass
class RuntimeAnalysis:
    """Structured extraction of runtime facts from incident evidence."""

    observed_failures: List[str] = field(default_factory=list)
    service: str = ""
    endpoint: Optional[str] = None
    exception_type: Optional[str] = None
    important_messages: List[str] = field(default_factory=list)
    request_ids: List[str] = field(default_factory=list)
    timeline: List[str] = field(default_factory=list)
    initial_hypotheses: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)


@dataclass
class CodeAnalysis:
    """Structured analysis of retrieved source code against runtime failure facts."""

    relevant_symbols: List[str] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    code_observations: List[str] = field(default_factory=list)
    possible_relationship_to_failure: List[str] = field(default_factory=list)
    missing_code_context: List[str] = field(default_factory=list)


@dataclass
class ChangeAnalysis:
    """Structured analysis of Git change history distinguishing facts from inferences."""

    relevant_changes: List[str] = field(default_factory=list)
    potential_relationships: List[str] = field(default_factory=list)
    timing_observations: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    uncertainty: List[str] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)
    inferences: List[str] = field(default_factory=list)


@dataclass
class RootCauseAnalysis:
    """Synthesized root-cause analysis grounded in concrete evidence citations."""

    failure_location: str = ""
    triggering_condition: str = ""
    root_cause_hypothesis: str = ""
    affected_component: str = ""  # Maintained for backward compatibility (mirrors failure_location)
    summary: str = ""
    supporting_evidence: List[EvidenceReference] = field(default_factory=list)
    contradicting_evidence: List[EvidenceReference] = field(default_factory=list)
    confidence: float = 0.0  # Model-assessed investigation confidence (0.0 to 1.0)
    uncertainties: List[str] = field(default_factory=list)


@dataclass
class RCAValidation:
    """Validation report challenging generated RCA claims against available evidence."""

    valid: bool = True
    issues: List[str] = field(default_factory=list)
    unsupported_claims: List[str] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)


@dataclass
class Investigation:
    """Aggregate domain model capturing the complete lifecycle and results of an investigation."""

    investigation_id: str
    incident_id: str
    status: InvestigationStatus
    created_at: datetime
    runtime_analysis: Optional[RuntimeAnalysis] = None
    code_query: Optional[str] = None
    code_results: List[Dict[str, Any]] = field(default_factory=list)
    code_analysis: Optional[CodeAnalysis] = None
    git_context: List[Dict[str, Any]] = field(default_factory=list)
    change_analysis: Optional[ChangeAnalysis] = None
    rca: Optional[RootCauseAnalysis] = None
    validation: Optional[RCAValidation] = None
    errors: List[str] = field(default_factory=list)
    completed_at: Optional[datetime] = None
