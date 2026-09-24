"""FastAPI HTTP routes for incident remediation proposals."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.agents.models import InvestigationNotFoundError
from app.incidents.service import IncidentNotFoundError
from app.remediation.dependencies import get_remediation_service, get_review_service
from app.remediation.models import (
    ProposedChangeSchema,
    RemediationBranch,
    RemediationBranchError,
    RemediationBranchResponseSchema,
    RemediationEvidenceReferenceSchema,
    RemediationIneligibleError,
    RemediationNotFoundError,
    RemediationProposal,
    RemediationProposalResponseSchema,
    RemediationReview,
    RemediationReviewCreateSchema,
    RemediationReviewError,
    RemediationReviewResponseSchema,
    RemediationValidationSchema,
)
from app.remediation.review_service import RemediationReviewService
from app.remediation.service import RemediationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incidents/{incident_id}/remediation", tags=["Remediation"])


def _review_to_response_schema(review: RemediationReview) -> RemediationReviewResponseSchema:
    """Helper converting domain RemediationReview to API response schema."""
    return RemediationReviewResponseSchema(
        review_id=review.review_id,
        incident_id=review.incident_id,
        remediation_id=review.remediation_id,
        investigation_id=review.investigation_id,
        decision=review.decision,
        reviewer=review.reviewer,
        comment=review.comment,
        created_at=review.created_at,
    )


def _branch_to_response_schema(branch: RemediationBranch) -> RemediationBranchResponseSchema:
    """Helper converting domain RemediationBranch to API response schema."""
    return RemediationBranchResponseSchema(
        branch_id=branch.branch_id,
        incident_id=branch.incident_id,
        remediation_id=branch.remediation_id,
        approval_id=branch.approval_id,
        branch_name=branch.branch_name,
        base_branch=branch.base_branch,
        base_commit=branch.base_commit,
        created_at=branch.created_at,
    )


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


@router.post(
    "/reviews",
    response_model=RemediationReviewResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a human review decision for an incident remediation proposal",
)
def submit_review(
    incident_id: str,
    payload: RemediationReviewCreateSchema,
    service: RemediationReviewService = Depends(get_review_service),
) -> RemediationReviewResponseSchema:
    """Records a human review decision (approved, rejected, revision_requested) for the active remediation proposal."""
    try:
        review = service.submit_review(incident_id=incident_id, payload=payload)
        return _review_to_response_schema(review)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvestigationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RemediationReviewError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/reviews",
    response_model=List[RemediationReviewResponseSchema],
    status_code=status.HTTP_200_OK,
    summary="Get full review audit trail for an incident",
)
def list_reviews(
    incident_id: str,
    service: RemediationReviewService = Depends(get_review_service),
) -> List[RemediationReviewResponseSchema]:
    """Retrieves chronological review history (newest first) for an incident's remediations."""
    try:
        reviews = service.list_reviews(incident_id=incident_id)
        return [_review_to_response_schema(r) for r in reviews]
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/branch",
    response_model=RemediationBranchResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create an isolated Git branch for an approved remediation",
)
def create_branch(
    incident_id: str,
    service: RemediationReviewService = Depends(get_review_service),
) -> RemediationBranchResponseSchema:
    """Creates an isolated Git branch (sentinel/incident-<id>-fix) pinned to base branch HEAD for approved remediation."""
    try:
        branch = service.create_branch(incident_id=incident_id)
        return _branch_to_response_schema(branch)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvestigationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RemediationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RemediationBranchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/branch",
    response_model=RemediationBranchResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Get active branch details for an incident",
)
def get_branch(
    incident_id: str,
    service: RemediationReviewService = Depends(get_review_service),
) -> RemediationBranchResponseSchema:
    """Retrieves active branch record for an incident."""
    try:
        branch = service.get_branch(incident_id=incident_id)
        if not branch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Branch for incident '{incident_id}' not found.",
            )
        return _branch_to_response_schema(branch)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
