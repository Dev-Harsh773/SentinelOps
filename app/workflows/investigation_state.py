"""Investigation state definition for LangGraph incident workflow."""

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict

from app.agents.models import (
    ChangeAnalysis,
    CodeAnalysis,
    RCAValidation,
    RootCauseAnalysis,
    RuntimeAnalysis,
)
from app.incidents.models import Incident
from app.telemetry.models import Evidence


class InvestigationState(TypedDict, total=False):
    """Shared state container passed between LangGraph investigation nodes."""

    incident: Incident
    runtime_evidence: List[Evidence]
    runtime_analysis: Optional[RuntimeAnalysis]
    code_query: Optional[str]
    code_results: List[Dict[str, Any]]
    code_analysis: Optional[CodeAnalysis]
    git_context: List[Dict[str, Any]]
    change_analysis: Optional[ChangeAnalysis]
    rca: Optional[RootCauseAnalysis]
    validation: Optional[RCAValidation]
    revision_count: int
    max_revisions: int
    errors: List[str]
