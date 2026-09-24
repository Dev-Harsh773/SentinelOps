"""FastAPI routes for SentinelOps incident investigations."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.dependencies import get_investigation_service
from app.agents.models import (
    Investigation,
    InvestigationLLMError,
    InvestigationNotFoundError,
    NoEvidenceForInvestigationError,
)
from app.agents.schemas import (
    ChangeAnalysisSchema,
    CodeAnalysisSchema,
    EvidenceReferenceSchema,
    InvestigationResponse,
    RCAValidationSchema,
    RootCauseAnalysisSchema,
    RuntimeAnalysisSchema,
)
from app.agents.service import InvestigationService
from app.incidents.service import IncidentNotFoundError
from app.memory.models import HistoricalIncidentContextSchema

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Investigation"])


def _to_response(inv: Investigation) -> InvestigationResponse:
    """Helper converting an Investigation domain entity to its API response schema."""
    ra_schema = None
    if inv.runtime_analysis:
        ra = inv.runtime_analysis
        ra_schema = RuntimeAnalysisSchema(
            observed_failures=ra.observed_failures,
            service=ra.service,
            endpoint=ra.endpoint,
            exception_type=ra.exception_type,
            important_messages=ra.important_messages,
            request_ids=ra.request_ids,
            timeline=ra.timeline,
            initial_hypotheses=ra.initial_hypotheses,
            missing_information=ra.missing_information,
        )

    ca_schema = None
    if inv.code_analysis:
        ca = inv.code_analysis
        ca_schema = CodeAnalysisSchema(
            relevant_symbols=ca.relevant_symbols,
            relevant_files=ca.relevant_files,
            code_observations=ca.code_observations,
            possible_relationship_to_failure=ca.possible_relationship_to_failure,
            missing_code_context=ca.missing_code_context,
        )

    cha_schema = None
    if inv.change_analysis:
        cha = inv.change_analysis
        cha_schema = ChangeAnalysisSchema(
            relevant_changes=cha.relevant_changes,
            potential_relationships=cha.potential_relationships,
            timing_observations=cha.timing_observations,
            contradictions=cha.contradictions,
            uncertainty=cha.uncertainty,
            facts=cha.facts,
            inferences=cha.inferences,
        )

    rca_schema = None
    if inv.rca:
        rca = inv.rca
        rca_schema = RootCauseAnalysisSchema(
            failure_location=rca.failure_location or rca.affected_component,
            triggering_condition=rca.triggering_condition,
            root_cause_hypothesis=rca.root_cause_hypothesis,
            affected_component=rca.affected_component or rca.failure_location,
            summary=rca.summary,
            supporting_evidence=[
                EvidenceReferenceSchema(type=ref.type, id=ref.id, description=ref.description)
                for ref in rca.supporting_evidence
            ],
            contradicting_evidence=[
                EvidenceReferenceSchema(type=ref.type, id=ref.id, description=ref.description)
                for ref in rca.contradicting_evidence
            ],
            confidence=rca.confidence,
            uncertainties=rca.uncertainties,
        )

    val_schema = None
    if inv.validation:
        val = inv.validation
        val_schema = RCAValidationSchema(
            valid=val.valid,
            issues=val.issues,
            unsupported_claims=val.unsupported_claims,
            missing_evidence=val.missing_evidence,
        )

    hist_schemas = [
        HistoricalIncidentContextSchema(
            incident_id=h.incident_id,
            title=h.title,
            service=h.service,
            failure_location=h.failure_location,
            triggering_condition=h.triggering_condition,
            root_cause_hypothesis=h.root_cause_hypothesis,
            similarity_score=h.similarity_score,
            matched_signals=h.matched_signals,
            resolution_notes=h.resolution_notes,
        )
        for h in getattr(inv, "historical_context", [])
    ]

    return InvestigationResponse(
        investigation_id=inv.investigation_id,
        incident_id=inv.incident_id,
        status=inv.status.value,
        created_at=inv.created_at,
        completed_at=inv.completed_at,
        runtime_analysis=ra_schema,
        code_query=inv.code_query,
        code_results=inv.code_results,
        code_analysis=ca_schema,
        git_context=inv.git_context,
        change_analysis=cha_schema,
        historical_context=hist_schemas,
        rca=rca_schema,
        validation=val_schema,
        errors=inv.errors,
    )


@router.post(
    "/incidents/{incident_id}/investigate",
    response_model=InvestigationResponse,
    status_code=status.HTTP_200_OK,
    summary="Run AI-assisted LangGraph investigation on an incident",
)
def investigate_incident(
    incident_id: str,
    service: InvestigationService = Depends(get_investigation_service),
) -> InvestigationResponse:
    """Executes the multi-node LangGraph investigation workflow.

    Combines incident metadata, attached runtime evidence, source-code retrieval,
    and Git change intelligence into an evidence-grounded root cause analysis.
    """
    try:
        investigation = service.investigate(incident_id=incident_id)
        return _to_response(investigation)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except NoEvidenceForInvestigationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvestigationLLMError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get(
    "/incidents/{incident_id}/investigation",
    response_model=InvestigationResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve the investigation results for an incident",
)
def get_incident_investigation(
    incident_id: str,
    service: InvestigationService = Depends(get_investigation_service),
) -> InvestigationResponse:
    """Returns the most recent investigation results for the specified incident."""
    try:
        investigation = service.get_investigation(incident_id=incident_id)
        return _to_response(investigation)
    except InvestigationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
