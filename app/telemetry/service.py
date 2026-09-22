"""Telemetry and Evidence business service for SentinelOps."""

from datetime import datetime, timezone
import os
from typing import List, Set
import uuid

from app.incidents.service import IncidentService
from app.telemetry.collector import RuntimeLogCollector
from app.telemetry.models import Evidence, EvidenceType
from app.telemetry.repository import EvidenceRepository
from app.telemetry.schemas import EvidenceCollectionResponse, EvidenceResponse

# Logical source identifier (decoupled from local machine filesystem paths)
LOGICAL_EVIDENCE_SOURCE = "demo-app-runtime-log"

# Set of event identifiers considered meaningful incident failure evidence for Stage 3
EVIDENCE_WORTHY_EVENTS: Set[str] = {
    "order_processing_failed",
}


class TelemetryService:
    """Orchestrates runtime evidence collection and attachment to SentinelOps incidents."""

    def __init__(
        self,
        incident_service: IncidentService,
        evidence_repository: EvidenceRepository,
        log_collector: RuntimeLogCollector,
        source_name: str = LOGICAL_EVIDENCE_SOURCE,
    ) -> None:
        self._incident_service = incident_service
        self._evidence_repository = evidence_repository
        self._log_collector = log_collector
        self._source_name = source_name

    def collect_evidence_for_incident(
        self, incident_id: str, request_id: str
    ) -> EvidenceCollectionResponse:
        """Collect runtime log evidence matching request_id and attach to an incident.

        Steps:
        1. Validate incident exists (raises IncidentNotFoundError -> HTTP 404).
           Incident status is strictly preserved without automatic modification.
        2. Check log source availability.
        3. Query log collector for raw events matching request_id.
        4. Filter for evidence-worthy events (e.g. order_processing_failed).
        5. Check existing fingerprints to avoid duplicate event ingestion.
        6. Persist new Evidence items and return summary response.
        """
        # Step 1: Validate incident exists (raises domain exception if not found)
        self._incident_service.get_incident(incident_id)

        # Step 2: Check log file availability
        if not os.path.exists(self._log_collector.log_path):
            return EvidenceCollectionResponse(
                incident_id=incident_id,
                request_id=request_id,
                collected=0,
                evidence=[],
                message="Runtime log source is not available.",
            )

        # Step 3: Collect raw runtime log events matching request_id
        raw_events = self._log_collector.collect_events_for_request(request_id)
        if not raw_events:
            return EvidenceCollectionResponse(
                incident_id=incident_id,
                request_id=request_id,
                collected=0,
                evidence=[],
                message="No matching runtime evidence found.",
            )

        # Step 4: Filter for evidence-worthy events (avoid polluting evidence with lifecycle noise)
        candidate_events = [
            e
            for e in raw_events
            if e.get("event") in EVIDENCE_WORTHY_EVENTS or e.get("level") == "ERROR"
        ]

        if not candidate_events:
            return EvidenceCollectionResponse(
                incident_id=incident_id,
                request_id=request_id,
                collected=0,
                evidence=[],
                message="No matching runtime evidence found.",
            )

        # Step 5: Check existing evidence fingerprints for duplicate prevention
        existing_fingerprints = self._evidence_repository.get_fingerprints_for_incident(incident_id)
        newly_created: List[Evidence] = []
        ingestion_time = datetime.now(timezone.utc)

        for raw_event in candidate_events:
            event_time: datetime = raw_event["_parsed_datetime"]
            exc_type = raw_event.get("exception_type")

            candidate_evidence = Evidence(
                id=str(uuid.uuid4()),
                incident_id=incident_id,
                type=EvidenceType.RUNTIME_LOG,
                source=self._source_name,
                timestamp=event_time,  # Runtime occurrence time
                service=raw_event.get("service", "unknown"),
                request_id=request_id,
                level=raw_event.get("level", "ERROR"),
                event=raw_event.get("event", "unknown"),
                message=raw_event.get("message", ""),
                endpoint=raw_event.get("endpoint"),
                exception_type=exc_type,
                metadata=raw_event.get("metadata", {}),
                created_at=ingestion_time,  # SentinelOps ingestion time
            )

            # Deduplication check
            if candidate_evidence.fingerprint() in existing_fingerprints:
                continue

            saved = self._evidence_repository.create(candidate_evidence)
            existing_fingerprints.add(saved.fingerprint())
            newly_created.append(saved)

        # Determine response message
        if not newly_created:
            message = "Matching evidence was already attached to this incident."
        else:
            message = f"Successfully collected {len(newly_created)} evidence item(s)."

        return EvidenceCollectionResponse(
            incident_id=incident_id,
            request_id=request_id,
            collected=len(newly_created),
            evidence=[EvidenceResponse.model_validate(e) for e in newly_created],
            message=message,
        )

    def list_evidence_for_incident(self, incident_id: str) -> List[Evidence]:
        """List all evidence attached to an incident after verifying incident exists."""
        self._incident_service.get_incident(incident_id)
        return self._evidence_repository.list_for_incident(incident_id)
