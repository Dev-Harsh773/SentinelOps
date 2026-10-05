"""FastAPI routes for Incident Report generation."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.incidents.service import IncidentNotFoundError
from app.reports.dependencies import get_report_service
from app.reports.schemas import IncidentReportResponse
from app.reports.service import ProjectIsolationError, ReportService

router = APIRouter(prefix="/incidents", tags=["Reports"])


@router.get(
    "/{incident_id}/report",
    response_model=IncidentReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Get unified incident report and chronological timeline",
)
def get_incident_report(
    incident_id: str,
    project_id: str = Query(..., description="Project ID matching authorized active project"),
    service: ReportService = Depends(get_report_service),
) -> IncidentReportResponse:
    """Returns a unified on-demand incident report and factual chronological timeline.
    
    Enforces project isolation: if the incident does not belong to the requested
    project_id, returns HTTP 404 to avoid cross-project existence leaks.
    """
    try:
        return service.generate_report(incident_id=incident_id, project_id=project_id)
    except IncidentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )
    except ProjectIsolationError:
        # Zero leakage: return 404 identical to non-existent incident
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found.",
        )
