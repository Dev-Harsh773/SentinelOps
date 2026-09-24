"""Service orchestrating human review decisions and isolated Git branch creation."""

from datetime import datetime, timezone
import logging
import re
from typing import List, Optional
import uuid

from app.agents.models import InvestigationNotFoundError, InvestigationStatus
from app.agents.service import InvestigationService
from app.incidents.service import IncidentNotFoundError, IncidentService
from app.remediation.branch_repository import RemediationBranchRepository
from app.remediation.models import (
    RemediationBranch,
    RemediationBranchError,
    RemediationNotFoundError,
    RemediationProposal,
    RemediationReview,
    RemediationReviewCreateSchema,
    RemediationReviewError,
    RemediationStatus,
    ReviewDecision,
)
from app.remediation.repository import RemediationRepository
from app.remediation.review_repository import RemediationReviewRepository
from app.repository.branch_manager import GitBranchManager

logger = logging.getLogger(__name__)


class RemediationReviewService:
    """Enforces human review lifecycle, audit trails, and isolated Git branch creation."""

    def __init__(
        self,
        remediation_repository: RemediationRepository,
        review_repository: RemediationReviewRepository,
        branch_repository: RemediationBranchRepository,
        incident_service: IncidentService,
        investigation_service: InvestigationService,
        git_branch_manager: GitBranchManager,
    ) -> None:
        self._remediation_repo = remediation_repository
        self._review_repo = review_repository
        self._branch_repo = branch_repository
        self._incident_service = incident_service
        self._investigation_service = investigation_service
        self._git_manager = git_branch_manager

    def submit_review(
        self,
        incident_id: str,
        payload: RemediationReviewCreateSchema,
    ) -> RemediationReview:
        """Submits a human review decision (approved, rejected, revision_requested) for a proposal."""
        # 1. Incident existence
        incident = self._incident_service.get_incident(incident_id)
        if not incident:
            raise IncidentNotFoundError(incident_id)

        # 2. Investigation existence
        investigation = self._investigation_service.get_investigation(incident_id)
        if not investigation:
            raise InvestigationNotFoundError(incident_id)

        # 3. Remediation proposal existence
        proposal = self._remediation_repo.get_by_incident_id(incident_id)
        if not proposal:
            raise RemediationNotFoundError(incident_id)

        # 4. Stale remediation check
        if proposal.investigation_id != investigation.investigation_id:
            raise RemediationReviewError(
                incident_id,
                "Remediation proposal is stale; an updated investigation exists.",
            )

        # 5. Check exact review idempotency FIRST (before any terminal/approved checks)
        latest_review = self._review_repo.get_latest_for_remediation(proposal.remediation_id)
        clean_reviewer = payload.reviewer.strip()
        clean_comment = payload.comment.strip()

        if (
            latest_review
            and latest_review.decision == payload.decision
            and latest_review.reviewer == clean_reviewer
            and latest_review.comment == clean_comment
        ):
            logger.info(
                "Identical review for remediation '%s' submitted; returning existing review idempotently",
                proposal.remediation_id,
            )
            return latest_review

        # 6. Lifecycle preconditions
        if proposal.status == RemediationStatus.DRAFT:
            raise RemediationReviewError(incident_id, "Cannot review remediation that is in draft status.")

        if proposal.status == RemediationStatus.FAILED_VALIDATION or (
            proposal.validation and not proposal.validation.valid
        ):
            raise RemediationReviewError(
                incident_id,
                "Cannot review remediation proposal that failed evidence grounding validation.",
            )

        if proposal.status == RemediationStatus.REJECTED:
            raise RemediationReviewError(
                incident_id,
                "Remediation proposal was rejected and cannot be approved. Generate a new proposal before reviewing.",
            )

        if proposal.status == RemediationStatus.REVISION_REQUESTED:
            raise RemediationReviewError(
                incident_id,
                "Remediation proposal has revisions requested. Generate an updated proposal before reviewing.",
            )

        if proposal.status == RemediationStatus.APPROVED:
            existing_branch = self._branch_repo.get_by_remediation_id(proposal.remediation_id)
            if existing_branch:
                raise RemediationReviewError(
                    incident_id,
                    "Remediation proposal has already been branched; approval cannot be altered.",
                )
            raise RemediationReviewError(incident_id, "Remediation proposal is already approved.")

        # 7. Apply review decision
        now = datetime.now(timezone.utc)
        review = RemediationReview(
            review_id=str(uuid.uuid4()),
            incident_id=incident_id,
            remediation_id=proposal.remediation_id,
            investigation_id=proposal.investigation_id,
            decision=payload.decision,
            reviewer=clean_reviewer,
            comment=clean_comment,
            created_at=now,
        )

        if payload.decision == ReviewDecision.APPROVED:
            proposal.status = RemediationStatus.APPROVED
        elif payload.decision == ReviewDecision.REJECTED:
            proposal.status = RemediationStatus.REJECTED
        elif payload.decision == ReviewDecision.REVISION_REQUESTED:
            proposal.status = RemediationStatus.REVISION_REQUESTED

        proposal.updated_at = now
        self._remediation_repo.save(proposal)
        self._review_repo.save(review)

        logger.info(
            "Recorded review '%s' (decision='%s') for remediation '%s'",
            review.review_id,
            review.decision.value,
            proposal.remediation_id,
        )
        return review

    def list_reviews(self, incident_id: str) -> List[RemediationReview]:
        """Returns the full chronological review audit trail for an incident (newest first)."""
        incident = self._incident_service.get_incident(incident_id)
        if not incident:
            raise IncidentNotFoundError(incident_id)

        return self._review_repo.list_for_incident(incident_id)

    def create_branch(self, incident_id: str) -> RemediationBranch:
        """Creates and checks out an isolated Git branch rooted at base branch HEAD for an approved remediation."""
        # 1. Incident existence
        incident = self._incident_service.get_incident(incident_id)
        if not incident:
            raise IncidentNotFoundError(incident_id)

        # 2. Investigation existence and eligibility
        investigation = self._investigation_service.get_investigation(incident_id)
        if not investigation:
            raise InvestigationNotFoundError(incident_id)

        inv_status = (
            investigation.status.value
            if hasattr(investigation.status, "value")
            else str(investigation.status)
        ).lower()
        if inv_status != InvestigationStatus.COMPLETED.value:
            raise RemediationBranchError(
                incident_id,
                f"Investigation status is '{inv_status}', expected '{InvestigationStatus.COMPLETED.value}'.",
            )

        if not investigation.validation or not investigation.validation.valid:
            raise RemediationBranchError(
                incident_id,
                "Investigation Root Cause Analysis failed evidence grounding validation.",
            )

        # 3. Remediation proposal existence
        proposal = self._remediation_repo.get_by_incident_id(incident_id)
        if not proposal:
            raise RemediationNotFoundError(incident_id)

        # 4. Stale remediation check
        if proposal.investigation_id != investigation.investigation_id:
            raise RemediationBranchError(
                incident_id,
                "Remediation proposal is stale; an updated investigation exists.",
            )

        # 5. Human approval verification
        if proposal.status != RemediationStatus.APPROVED:
            raise RemediationBranchError(
                incident_id,
                f"Remediation proposal status is '{proposal.status.value}', expected '{RemediationStatus.APPROVED.value}'.",
            )

        latest_review = self._review_repo.get_latest_for_remediation(proposal.remediation_id)
        if not latest_review or latest_review.decision != ReviewDecision.APPROVED:
            raise RemediationBranchError(
                incident_id,
                "No approved human review found authorizing branch creation for this remediation proposal.",
            )

        # 6. Branch idempotency without checkout side effects
        existing_branch = self._branch_repo.get_by_remediation_id(proposal.remediation_id)
        if existing_branch:
            if self._git_manager.branch_exists(existing_branch.branch_name):
                logger.info(
                    "Branch '%s' already exists for remediation '%s'; returning existing record idempotently without checkout",
                    existing_branch.branch_name,
                    proposal.remediation_id,
                )
                return existing_branch

        # 7. Deterministic sanitized branch naming
        clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "-", incident_id.lower()).strip("-")
        clean_id = re.sub(r"-+", "-", clean_id)
        branch_name = f"sentinel/incident-{clean_id}-fix"[:100]

        # 8. Unassociated branch collision protection
        if self._git_manager.branch_exists(branch_name):
            raise RemediationBranchError(
                incident_id,
                f"Git branch '{branch_name}' already exists in repository; refuse to overwrite.",
            )

        # 9. Verify current Git branch equals configured trusted base branch
        current_branch = self._git_manager.get_current_branch()
        if current_branch != self._git_manager.base_branch:
            raise RemediationBranchError(
                incident_id,
                f"Repository is on branch '{current_branch}', but remediation branches must be created "
                f"from configured base branch '{self._git_manager.base_branch}'. Refusing to branch from an arbitrary active branch.",
            )

        # 10. Verify clean working tree (no uncommitted tracked modifications)
        if not self._git_manager.check_working_tree_clean():
            raise RemediationBranchError(
                incident_id,
                "Working tree has uncommitted modifications in tracked files. Refusing branch creation "
                "to prevent state corruption. Commit or stash changes before creating a remediation branch.",
            )

        # 11. Resolve base commit SHA from current HEAD of base branch
        base_commit = self._git_manager.get_head_commit()

        # 12. Create and switch to isolated branch
        self._git_manager.create_and_checkout_branch(branch_name=branch_name, base_commit=base_commit)

        # 13. Persist branch entity
        branch = RemediationBranch(
            branch_id=str(uuid.uuid4()),
            incident_id=incident_id,
            remediation_id=proposal.remediation_id,
            approval_id=latest_review.review_id,
            branch_name=branch_name,
            base_branch=current_branch,
            base_commit=base_commit,
            created_at=datetime.now(timezone.utc),
        )
        self._branch_repo.save(branch)

        logger.info(
            "Created isolated branch '%s' for incident '%s' authorized by review '%s'",
            branch_name,
            incident_id,
            latest_review.review_id,
        )
        return branch

    def get_branch(self, incident_id: str) -> Optional[RemediationBranch]:
        """Retrieves active branch record for an incident if present."""
        incident = self._incident_service.get_incident(incident_id)
        if not incident:
            raise IncidentNotFoundError(incident_id)

        return self._branch_repo.get_by_incident_id(incident_id)
