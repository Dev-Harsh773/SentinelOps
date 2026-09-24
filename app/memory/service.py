"""Incident memory service orchestrating ingestion and historical context retrieval."""

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.memory.matcher import IncidentMemoryMatcher
from app.memory.models import (
    HistoricalIncidentContext,
    HistoricalSearchQuery,
    IncidentMemory,
)
from app.memory.repository import IncidentMemoryRepository

logger = logging.getLogger(__name__)


class IncidentMemoryService:
    """Service managing trusted incident memories and deterministic historical retrieval."""

    def __init__(
        self,
        repository: IncidentMemoryRepository,
        matcher: Optional[IncidentMemoryMatcher] = None,
    ) -> None:
        self._repository = repository
        self._matcher = matcher or IncidentMemoryMatcher()

    def ingest_investigation(
        self,
        investigation: Any,
        incident: Any,
        resolution_notes: Optional[str] = None,
    ) -> Optional[IncidentMemory]:
        """Conditionally ingests an investigation into historical memory.

        Strict eligibility:
        - status == COMPLETED
        - rca is not None
        - validation is not None and validation.valid is True
        Never ingests intermediate, failed, or ungrounded/invalid investigations.
        Maintains exactly one trusted memory record per incident_id.
        """
        # Strict validation of eligibility
        status_val = (
            investigation.status.value
            if hasattr(investigation.status, "value")
            else str(investigation.status)
        ).lower()
        if status_val != "completed":
            logger.info(
                "Skipping memory ingestion for incident %s: status is '%s', expected 'completed'.",
                incident.id,
                status_val,
            )
            return None

        if not investigation.rca:
            logger.info("Skipping memory ingestion for incident %s: no RCA synthesized.", incident.id)
            return None

        if not investigation.validation or not investigation.validation.valid:
            logger.info("Skipping memory ingestion for incident %s: RCA validation failed or absent.", incident.id)
            return None

        now = datetime.now(timezone.utc)
        rca = investigation.rca
        ra = getattr(investigation, "runtime_analysis", None)
        ca = getattr(investigation, "code_analysis", None)

        failure_location = rca.failure_location or rca.affected_component
        endpoint = ra.endpoint if ra else None
        exception_type = ra.exception_type if ra else None
        relevant_symbols = list(ca.relevant_symbols) if ca and ca.relevant_symbols else []
        relevant_files = list(ca.relevant_files) if ca and ca.relevant_files else []

        existing = self._repository.get_by_incident_id(incident.id)
        if existing:
            logger.info("Refreshing existing trusted memory for incident %s.", incident.id)
            existing.service = incident.service
            existing.environment = incident.environment
            existing.title = incident.title
            existing.failure_location = failure_location
            existing.triggering_condition = rca.triggering_condition
            existing.root_cause_hypothesis = rca.root_cause_hypothesis
            existing.summary = rca.summary
            existing.endpoint = endpoint
            existing.exception_type = exception_type
            existing.relevant_symbols = relevant_symbols
            existing.relevant_files = relevant_files
            existing.investigation_id = investigation.investigation_id
            if resolution_notes is not None:
                existing.resolution_notes = resolution_notes
            existing.updated_at = now
            return self._repository.save(existing)

        logger.info("Ingesting new trusted memory for incident %s.", incident.id)
        new_memory = IncidentMemory(
            incident_id=incident.id,
            service=incident.service,
            environment=incident.environment,
            title=incident.title,
            failure_location=failure_location,
            triggering_condition=rca.triggering_condition,
            root_cause_hypothesis=rca.root_cause_hypothesis,
            summary=rca.summary,
            endpoint=endpoint,
            exception_type=exception_type,
            relevant_symbols=relevant_symbols,
            relevant_files=relevant_files,
            resolution_notes=resolution_notes,
            investigation_id=investigation.investigation_id,
            created_at=now,
            updated_at=now,
        )
        return self._repository.save(new_memory)

    def search_history(self, query: HistoricalSearchQuery) -> List[HistoricalIncidentContext]:
        """Retrieves and ranks relevant historical incident memories deterministically."""
        candidates = self._repository.list_all()
        return self._matcher.match(query, candidates)

    def get_memory(self, incident_id: str) -> Optional[IncidentMemory]:
        """Retrieves trusted memory for an incident if present."""
        return self._repository.get_by_incident_id(incident_id)

    def list_memories(self) -> List[IncidentMemory]:
        """Lists all stored trusted incident memories."""
        return self._repository.list_all()
