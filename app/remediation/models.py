"""Domain models, exceptions, and API schemas for SentinelOps remediation proposals."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.agents.models import EvidenceReference


# =====================================================================
# Domain Exceptions
# =====================================================================


class RemediationNotFoundError(Exception):
    """Raised when no remediation proposal exists for an incident."""

    def __init__(self, incident_id: str):
        super().__init__(f"No remediation proposal found for incident '{incident_id}'.")
        self.incident_id = incident_id


class RemediationIneligibleError(Exception):
    """Raised when an incident's investigation is not eligible for remediation."""

    def __init__(self, incident_id: str, reason: str):
        super().__init__(f"Incident '{incident_id}' is not eligible for remediation: {reason}")
        self.incident_id = incident_id
        self.reason = reason


# =====================================================================
# Domain Enums & Dataclasses
# =====================================================================


class RemediationStatus(str, Enum):
    """Lifecycle status of a remediation proposal."""

    DRAFT = "draft"
    VALIDATED = "validated"
    FAILED_VALIDATION = "failed_validation"


class ChangeType(str, Enum):
    """Classification of proposed remediation change."""

    MODIFY = "modify"
    ADD = "add"
    REMOVE = "remove"
    CONFIGURATION = "configuration"


@dataclass
class ProposedChange:
    """Discrete structured code or configuration change recommendation."""

    file_path: str
    change_type: ChangeType
    description: str
    reason: str
    symbol: Optional[str] = None


@dataclass
class RemediationValidation:
    """Detailed report on deterministic grounding and completeness validation."""

    valid: bool = True
    issues: List[str] = field(default_factory=list)
    unsupported_files: List[str] = field(default_factory=list)
    unsupported_symbols: List[str] = field(default_factory=list)
    missing_elements: List[str] = field(default_factory=list)


@dataclass
class RemediationProposal:
    """Aggregate domain model for an evidence-grounded remediation recommendation."""

    remediation_id: str
    incident_id: str
    investigation_id: str
    status: RemediationStatus
    summary: str
    target_files: List[str]
    target_symbols: List[str]
    proposed_changes: List[ProposedChange]
    rationale: str
    risks: List[str]
    validation_steps: List[str]
    evidence_references: List[EvidenceReference]
    validation: Optional[RemediationValidation] = None
    assumptions: List[str] = field(default_factory=list)
    advisory_historical_context: List[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =====================================================================
# API Request & Response Schemas
# =====================================================================


class ProposedChangeSchema(BaseModel):
    """API schema for a structured proposed change item."""

    file_path: str = Field(description="Repository-relative target file path")
    change_type: ChangeType = Field(description="Type of change: modify, add, remove, configuration")
    description: str = Field(description="Description of what should be changed")
    reason: str = Field(description="Rationale explaining why this change addresses the RCA")
    symbol: Optional[str] = Field(default=None, description="Targeted class or function symbol, if applicable")


class RemediationEvidenceReferenceSchema(BaseModel):
    """Schema for referencing evidence supporting remediation provenance."""

    type: str = Field(description="Evidence type: 'runtime', 'code', or 'git_commit'")
    id: str = Field(description="Stable evidence identifier from current investigation")
    description: Optional[str] = Field(default=None, description="Description of the cited evidence")


class RemediationValidationSchema(BaseModel):
    """API schema for remediation proposal validation results."""

    valid: bool = Field(description="True if remediation proposal meets all grounding constraints")
    issues: List[str] = Field(default_factory=list, description="List of identified validation flaws")
    unsupported_files: List[str] = Field(default_factory=list, description="Target files not retrieved in investigation")
    unsupported_symbols: List[str] = Field(default_factory=list, description="Symbols not found in retrieved source")
    missing_elements: List[str] = Field(default_factory=list, description="Required proposal elements that were omitted")


class RemediationProposalResponseSchema(BaseModel):
    """API response schema for a remediation proposal."""

    remediation_id: str
    incident_id: str
    investigation_id: str
    status: RemediationStatus
    summary: str
    target_files: List[str]
    target_symbols: List[str]
    proposed_changes: List[ProposedChangeSchema]
    rationale: str
    risks: List[str]
    validation_steps: List[str]
    evidence_references: List[RemediationEvidenceReferenceSchema]
    validation: Optional[RemediationValidationSchema] = None
    assumptions: List[str] = Field(default_factory=list)
    advisory_historical_context: List[str] = Field(default_factory=list)
    confidence: float
    created_at: datetime
    updated_at: datetime
