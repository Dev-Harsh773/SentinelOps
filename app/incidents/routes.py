"""FastAPI HTTP routes for Incident domain operations."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.incidents.dependencies import get_incident_service
from app.incidents.schemas import (
    IncidentCreateRequest,
    IncidentResponse,
    IncidentStatusUpdateRequest,
)
from app.incidents.service import (
    IncidentNotFoundError,
    IncidentService,
    InvalidStatusTransitionError,
)

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new incident",
)
def create_incident(
    payload: IncidentCreateRequest,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Create a new incident in OPEN status with UTC timestamp."""
    incident = service.create_incident(payload)
    return IncidentResponse.model_validate(incident)


@router.get(
    "",
    response_model=List[IncidentResponse],
    status_code=status.HTTP_200_OK,
    summary="List all incidents",
)
def list_incidents(
    service: IncidentService = Depends(get_incident_service),
) -> List[IncidentResponse]:
    """Retrieve all active and recorded incidents."""
    incidents = service.list_incidents()
    return [IncidentResponse.model_validate(i) for i in incidents]


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an incident by ID",
)
def get_incident(
    incident_id: str,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Retrieve a single incident by its UUID."""
    try:
        incident = service.get_incident(incident_id)
        return IncidentResponse.model_validate(incident)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.patch(
    "/{incident_id}/status",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update incident lifecycle status",
)
def update_incident_status(
    incident_id: str,
    payload: IncidentStatusUpdateRequest,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Validate and transition an incident's lifecycle status."""
    try:
        incident = service.update_status(incident_id, payload.status)
        return IncidentResponse.model_validate(incident)
    except IncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
