"""Remediation service orchestrating proposal generation, validation, and lifecycle."""

from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from app.agents.models import InvestigationNotFoundError, InvestigationStatus
from app.agents.service import InvestigationService
from app.incidents.service import IncidentNotFoundError, IncidentService
from app.remediation.llm import RemediationLLM
from app.remediation.models import (
    RemediationIneligibleError,
    RemediationNotFoundError,
    RemediationProposal,
    RemediationStatus,
)
from app.remediation.repository import RemediationRepository
from app.remediation.validator import RemediationValidator
from app.telemetry.repository import EvidenceRepository

logger = logging.getLogger(__name__)


class RemediationService:
    """Domain service coordinating remediation proposal generation and deterministic validation."""

    def __init__(
        self,
        remediation_repository: RemediationRepository,
        incident_service: IncidentService,
        investigation_service: InvestigationService,
        evidence_repository: EvidenceRepository,
        llm: RemediationLLM,
        validator: Optional[RemediationValidator] = None,
    ) -> None:
        self._repository = remediation_repository
        self._incident_service = incident_service
        self._investigation_service = investigation_service
        self._evidence_repository = evidence_repository
        self._llm = llm
        self._validator = validator or RemediationValidator()

    def get_remediation(self, incident_id: str) -> RemediationProposal:
        """Retrieve the active remediation proposal for an incident."""
        incident = self._incident_service.get_incident(incident_id)
        if not incident:
            raise IncidentNotFoundError(incident_id)

        proposal = self._repository.get_by_incident_id(incident_id)
        if not proposal:
            raise RemediationNotFoundError(incident_id)

        return proposal

    def propose_remediation(
        self,
        incident_id: str,
        regenerate: bool = False,
    ) -> RemediationProposal:
        """Generates an evidence-grounded remediation proposal for an incident.

        Eligibility Rules:
        - Incident must exist
        - Investigation must exist
        - Investigation must be COMPLETED
        - Investigation RCA must not be None
        - Investigation RCA validation must be valid

        Idempotency Rules:
        - If existing proposal exists for the exact same investigation_id and regenerate=False,
          return existing proposal unchanged.
        - If a newer validated investigation exists for the incident, automatically generate
          a fresh proposal (new remediation_id, new timestamps, overwrites active proposal).
        - If same investigation and regenerate=True, refresh proposal in place
          (preserve remediation_id and created_at, update updated_at).
        """
        # Step 1: Validate incident existence
        incident = self._incident_service.get_incident(incident_id)
        if not incident:
            logger.warning("Remediation requested for non-existent incident '%s'", incident_id)
            raise IncidentNotFoundError(incident_id)

        # Step 2: Validate investigation existence
        investigation = self._investigation_service.get_investigation(incident_id)
        if not investigation:
            logger.warning("Remediation requested for incident '%s' without an investigation", incident_id)
            raise InvestigationNotFoundError(incident_id)

        # Step 3: Validate eligibility
        status_val = (
            investigation.status.value
            if hasattr(investigation.status, "value")
            else str(investigation.status)
        ).lower()

        if status_val != InvestigationStatus.COMPLETED.value:
            raise RemediationIneligibleError(
                incident_id,
                f"Investigation status is '{status_val}', expected '{InvestigationStatus.COMPLETED.value}'.",
            )

        if not investigation.rca:
            raise RemediationIneligibleError(
                incident_id,
                "Investigation contains no synthesized Root Cause Analysis (RCA).",
            )

        if not investigation.validation or not investigation.validation.valid:
            raise RemediationIneligibleError(
                incident_id,
                "Investigation Root Cause Analysis failed evidence grounding validation.",
            )

        # Step 4: Check existing proposal for idempotency vs re-investigation refresh
        existing = self._repository.get_by_incident_id(incident_id)
        if existing and existing.investigation_id == investigation.investigation_id:
            if not regenerate:
                logger.info(
                    "Returning existing remediation proposal '%s' idempotently for incident '%s'",
                    existing.remediation_id,
                    incident_id,
                )
                return existing

            if existing.status == RemediationStatus.APPROVED:
                raise RemediationIneligibleError(
                    incident_id,
                    "Remediation proposal is already approved; regeneration is refused to prevent replacing an authorized proposal under active remediation.",
                )

        # Step 5: Gather current investigation evidence and context
        runtime_evidence = self._evidence_repository.list_for_incident(incident_id)
        code_chunks = investigation.code_results
        git_context = investigation.git_context
        historical_context = getattr(investigation, "historical_context", [])

        # Step 6: Generate initial remediation recommendation
        logger.info(
            "Generating remediation proposal for incident '%s' (investigation '%s')",
            incident_id,
            investigation.investigation_id,
        )
        proposal = self._llm.propose_remediation(
            incident=incident,
            investigation=investigation,
            runtime_evidence=runtime_evidence,
            code_chunks=code_chunks,
            git_context=git_context,
            historical_context=historical_context,
        )

        # Step 7: Deterministic Grounding & Completeness Validation
        val_report = self._validator.validate(
            proposal=proposal,
            investigation=investigation,
            runtime_evidence=runtime_evidence,
            code_chunks=code_chunks,
            git_context=git_context,
        )

        # Bounded 1-pass revision if initial generation is invalid
        if not val_report.valid:
            logger.info(
                "Remediation proposal failed initial validation with %d issues; triggering bounded revision.",
                len(val_report.issues),
            )
            proposal = self._llm.revise_remediation(
                proposal=proposal,
                validation=val_report,
                incident=incident,
                investigation=investigation,
                runtime_evidence=runtime_evidence,
                code_chunks=code_chunks,
                git_context=git_context,
                historical_context=historical_context,
            )
            # Re-validate revised proposal
            val_report = self._validator.validate(
                proposal=proposal,
                investigation=investigation,
                runtime_evidence=runtime_evidence,
                code_chunks=code_chunks,
                git_context=git_context,
            )

        # Persist full validation report on proposal
        proposal.validation = val_report
        if val_report.valid:
            proposal.status = RemediationStatus.VALIDATED
        else:
            proposal.status = RemediationStatus.FAILED_VALIDATION
            logger.warning(
                "Remediation proposal for incident '%s' failed validation after revision: %s",
                incident_id,
                val_report.issues,
            )

        # Step 8: Handle timestamps and ID according to idempotency / re-investigation rules
        now = datetime.now(timezone.utc)
        if (
            existing
            and existing.investigation_id == investigation.investigation_id
            and regenerate
            and existing.status == RemediationStatus.VALIDATED
        ):
            # Same investigation refreshed in place while still in VALIDATED status: preserve ID and created_at
            proposal.remediation_id = existing.remediation_id
            proposal.created_at = existing.created_at
            proposal.updated_at = now
        else:
            # Newer investigation, new proposal, or regeneration after REJECTED / REVISION_REQUESTED:
            # create a brand-new proposal with new remediation_id and new timestamps
            proposal.remediation_id = str(uuid.uuid4())
            proposal.created_at = now
            proposal.updated_at = now

        proposal.incident_id = incident.id
        proposal.investigation_id = investigation.investigation_id

        # Step 9: Save and return
        self._repository.save(proposal)
        logger.info(
            "Saved remediation proposal '%s' for incident '%s' with status '%s'",
            proposal.remediation_id,
            incident_id,
            proposal.status.value,
        )
        return proposal
