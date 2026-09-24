"""FastAPI HTTP routes for incident remediation proposals."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.agents.models import InvestigationNotFoundError
from app.incidents.service import IncidentNotFoundError
from app.remediation.dependencies import get_remediation_service
from app.remediation.models import (
    ProposedChangeSchema,
    RemediationEvidenceReferenceSchema,
    RemediationIneligibleError,
    RemediationNotFoundError,
    RemediationProposal,
    RemediationProposalResponseSchema,
    RemediationValidationSchema,
)
from app.remediation.service import RemediationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incidents/{incident_id}/remediation", tags=["Remediation"])


def _to_response_schema(proposal: RemediationProposal) -> RemediationProposalResponseSchema:
    """Helper converting domain RemediationProposal to API response schema."""
    val_schema = None
    if proposal.validation:
        val_schema = RemediationValidationSchema(
            valid=proposal.validation.valid,
            issues=proposal.validation.issues,
            unsupported_files=proposal.validation.unsupported_files,
            unsupported_symbols=proposal.validation.unsupported_symbols,
            missing_elements=proposal.validation.missing_elements,
        )

    return RemediationProposalResponseSchema(
        remediation_id=proposal.remediation_id,
        incident_id=proposal.incident_id,
        investigation_id=proposal.investigation_id,
        status=proposal.status,
        summary=proposal.summary,
        target_files=proposal.target_files,
        target_symbols=proposal.target_symbols,
        proposed_changes=[
            ProposedChangeSchema(
                file_path=pc.file_path,
                change_type=pc.change_type,
                description=pc.description,
                reason=pc.reason,
                symbol=pc.symbol,
            )
            for pc in proposal.proposed_changes
        ],
        rationale=proposal.rationale,
        risks=proposal.risks,
        validation_steps=proposal.validation_steps,
        evidence_references=[
            RemediationEvidenceReferenceSchema(
                type=ref.type,
                id=ref.id,
                description=ref.description,
            )
            for ref in proposal.evidence_references
        ],
        validation=val_schema,
        assumptions=proposal.assumptions,
        advisory_historical_context=proposal.advisory_historical_context,
        confidence=proposal.confidence,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


@router.post(
    "",
    response_model=RemediationProposalResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Generate or retrieve remediation proposal for an incident",
)
def propose_remediation(
    incident_id: str,
    regenerate: bool = Query(default=False, description="Force regeneration even if proposal exists"),
    service: RemediationService = Depends(get_remediation_service),
) -> RemediationProposalResponseSchema:
    """Generates an evidence-grounded remediation recommendation addressing the incident's RCA."""
    try:
        proposal = service.propose_remediation(incident_id=incident_id, regenerate=regenerate)
        return _to_response_schema(proposal)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvestigationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RemediationIneligibleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "",
    response_model=RemediationProposalResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Get active remediation proposal for an incident",
)
def get_remediation(
    incident_id: str,
    service: RemediationService = Depends(get_remediation_service),
) -> RemediationProposalResponseSchema:
    """Retrieves the existing remediation proposal for an incident."""
    try:
        proposal = service.get_remediation(incident_id=incident_id)
        return _to_response_schema(proposal)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
