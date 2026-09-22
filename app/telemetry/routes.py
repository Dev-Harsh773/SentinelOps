"""FastAPI HTTP routes for incident telemetry and evidence collection."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.incidents.service import IncidentNotFoundError
from app.telemetry.dependencies import get_telemetry_service
from app.telemetry.schemas import (
    EvidenceCollectionResponse,
    EvidenceCollectRequest,
    EvidenceResponse,
)
from app.telemetry.service import TelemetryService

router = APIRouter(prefix="/incidents/{incident_id}/evidence", tags=["Telemetry & Evidence"])


@router.post(
    "/collect",
    response_model=EvidenceCollectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Collect runtime log evidence for an incident by request ID",
)
def collect_evidence(
    incident_id: str,
    payload: EvidenceCollectRequest,
    service: TelemetryService = Depends(get_telemetry_service),
) -> EvidenceCollectionResponse:
    """Search runtime JSONL logs for events matching request_id and attach as incident evidence."""
    try:
        return service.collect_evidence_for_incident(
            incident_id=incident_id, request_id=payload.request_id
        )
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "",
    response_model=List[EvidenceResponse],
    status_code=status.HTTP_200_OK,
    summary="List all evidence items attached to an incident",
)
def list_incident_evidence(
    incident_id: str,
    service: TelemetryService = Depends(get_telemetry_service),
) -> List[EvidenceResponse]:
    """Retrieve all evidence records currently attached to an incident."""
    try:
        evidence_list = service.list_evidence_for_incident(incident_id)
        return [EvidenceResponse.model_validate(e) for e in evidence_list]
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
