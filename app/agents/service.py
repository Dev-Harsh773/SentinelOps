"""Investigation domain service coordinating the LangGraph investigation workflow."""

from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from app.agents.llm import InvestigationLLM
from app.agents.models import (
    Investigation,
    InvestigationNotFoundError,
    InvestigationStatus,
    NoEvidenceForInvestigationError,
)
from app.agents.repository import InvestigationRepository
from app.incidents.service import IncidentNotFoundError, IncidentService
from app.repository.service import GitService
from app.retrieval.service import RetrievalService
from app.telemetry.repository import EvidenceRepository
from app.workflows.investigation_graph import build_investigation_graph
from app.workflows.investigation_state import InvestigationState

logger = logging.getLogger(__name__)


class InvestigationService:
    """Domain service orchestrating AI-assisted incident investigations.

    Coordinates incident retrieval, evidence verification, graph compilation,
    deterministic tool execution, LLM reasoning, validation, and storage.
    """

    def __init__(
        self,
        investigation_repository: InvestigationRepository,
        incident_service: IncidentService,
        evidence_repository: EvidenceRepository,
        retrieval_service: RetrievalService,
        git_service: GitService,
        llm: InvestigationLLM,
        git_limit: int = 3,
        max_revisions: int = 1,
    ) -> None:
        self._investigation_repository = investigation_repository
        self._incident_service = incident_service
        self._evidence_repository = evidence_repository
        self._retrieval_service = retrieval_service
        self._git_service = git_service
        self._llm = llm
        self._git_limit = git_limit
        self._max_revisions = max_revisions

    def investigate(self, incident_id: str) -> Investigation:
        """Runs the LangGraph investigation workflow for an existing incident.

        Args:
            incident_id: Unique identifier of the incident to investigate.

        Returns:
            Completed Investigation entity containing structured RCA and evidence grounding.

        Raises:
            IncidentNotFoundError: If the incident does not exist.
            NoEvidenceForInvestigationError: If the incident has no attached runtime evidence.
        """
        # Step 1: Validate incident existence
        incident = self._incident_service.get_incident(incident_id)
        if not incident:
            logger.warning("Investigation attempted for non-existent incident '%s'", incident_id)
            raise IncidentNotFoundError(incident_id)

        # Step 2: Validate attached runtime evidence presence
        evidence_list = self._evidence_repository.list_for_incident(incident_id)
        if not evidence_list:
            logger.warning("Incident '%s' has 0 attached evidence records; aborting.", incident_id)
            raise NoEvidenceForInvestigationError(incident_id)

        investigation_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        logger.info(
            "Starting investigation %s for incident %s (%d evidence items)",
            investigation_id,
            incident_id,
            len(evidence_list),
        )

        # Step 3: Build LangGraph workflow runnable
        graph = build_investigation_graph(
            llm=self._llm,
            retrieval_service=self._retrieval_service,
            git_service=self._git_service,
            git_limit=self._git_limit,
            max_revisions=self._max_revisions,
        )

        initial_state: InvestigationState = {
            "incident": incident,
            "runtime_evidence": evidence_list,
            "runtime_analysis": None,
            "code_query": None,
            "code_results": [],
            "code_analysis": None,
            "git_context": [],
            "change_analysis": None,
            "rca": None,
            "validation": None,
            "revision_count": 0,
            "max_revisions": self._max_revisions,
            "errors": [],
        }

        # Step 4: Execute graph synchronously
        final_state = graph.invoke(initial_state)

        rca = final_state.get("rca")
        validation = final_state.get("validation")
        errors = list(final_state.get("errors", []))

        if rca is not None and validation is not None and validation.valid is True:
            status = InvestigationStatus.COMPLETED
        else:
            status = InvestigationStatus.FAILED
            if validation is not None and not validation.valid:
                raw_reasons: List[str] = []
                for cat in (validation.issues, validation.unsupported_claims, validation.missing_evidence):
                    if cat:
                        for r in cat:
                            r_clean = str(r).strip()
                            if r_clean and r_clean not in raw_reasons:
                                raw_reasons.append(r_clean)
                if raw_reasons:
                    validation_err = f"RCA validation failed: {'; '.join(raw_reasons)}"
                else:
                    validation_err = "RCA validation failed"
                if validation_err not in errors:
                    errors.append(validation_err)
        completed_at = datetime.now(timezone.utc)

        investigation = Investigation(
            investigation_id=investigation_id,
            incident_id=incident_id,
            status=status,
            created_at=created_at,
            completed_at=completed_at,
            runtime_analysis=final_state.get("runtime_analysis"),
            code_query=final_state.get("code_query"),
            code_results=final_state.get("code_results", []),
            code_analysis=final_state.get("code_analysis"),
            git_context=final_state.get("git_context", []),
            change_analysis=final_state.get("change_analysis"),
            rca=rca,
            validation=final_state.get("validation"),
            errors=errors,
        )

        # Step 5: Save and return
        self._investigation_repository.save(investigation)
        logger.info("Investigation %s finished with status %s", investigation_id, status.value)
        return investigation

    def get_investigation(self, incident_id: str) -> Investigation:
        """Retrieves an existing investigation for an incident.

        Args:
            incident_id: The incident identifier.

        Returns:
            Investigation domain entity.

        Raises:
            InvestigationNotFoundError: If no investigation has been run for this incident.
        """
        investigation = self._investigation_repository.get_by_incident_id(incident_id)
        if not investigation:
            raise InvestigationNotFoundError(incident_id)
        return investigation
