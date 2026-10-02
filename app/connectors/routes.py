"""FastAPI HTTP routes for Connectors onboarding, configuration, ingestion, and collection."""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.connectors.auth import WebhookAuthenticationError
from app.connectors.dependencies import get_connector_service
from app.connectors.models import (
    ConnectorCreateRequest,
    ConnectorResponse,
    ConnectorUpdateRequest,
    WebhookIngestRequest,
)
from app.connectors.service import (
    ConnectorDisabledError,
    ConnectorService,
    InvalidConnectorOperationError,
)
from app.connectors.store import ConnectorNotFoundError, DuplicateConnectorIdError
from app.projects.storage import ProjectNotFoundError

router = APIRouter(prefix="/connectors", tags=["Connectors"])


@router.post(
    "",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new telemetry or deployment connector",
)
async def create_connector(
    payload: ConnectorCreateRequest,
    service: ConnectorService = Depends(get_connector_service),
) -> ConnectorResponse:
    """Create a new connector bound to an onboarded project."""
    try:
        return await service.create_connector(payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DuplicateConnectorIdError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get(
    "",
    response_model=List[ConnectorResponse],
    status_code=status.HTTP_200_OK,
    summary="List all connectors",
)
def list_connectors(
    project_id: Optional[str] = Query(default=None, description="Filter by project_id"),
    service: ConnectorService = Depends(get_connector_service),
) -> List[ConnectorResponse]:
    """List registered connectors with sensitive secrets masked."""
    return service.list_connectors(project_id=project_id)


@router.get(
    "/{connector_id}",
    response_model=ConnectorResponse,
    status_code=status.HTTP_200_OK,
    summary="Get connector by ID",
)
def get_connector(
    connector_id: str,
    service: ConnectorService = Depends(get_connector_service),
) -> ConnectorResponse:
    """Retrieve connector details and current health status."""
    try:
        return service.get_connector(connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.put(
    "/{connector_id}",
    response_model=ConnectorResponse,
    status_code=status.HTTP_200_OK,
    summary="Update connector configuration",
)
async def update_connector(
    connector_id: str,
    payload: ConnectorUpdateRequest,
    service: ConnectorService = Depends(get_connector_service),
) -> ConnectorResponse:
    """Update connector configuration, preserving existing secrets if masked."""
    try:
        return await service.update_connector(connector_id, payload)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.delete(
    "/{connector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a connector",
)
async def delete_connector(
    connector_id: str,
    service: ConnectorService = Depends(get_connector_service),
) -> None:
    """Delete a connector and cancel any active polling workers."""
    try:
        await service.delete_connector(connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{connector_id}/ingest",
    status_code=status.HTTP_200_OK,
    summary="Ingest webhook telemetry",
)
async def ingest_webhook(
    connector_id: str,
    request: Request,
    service: ConnectorService = Depends(get_connector_service),
) -> Dict[str, Any]:
    """Ingest external webhook payload following Option B deduplication and strict status semantics."""
    raw_body = await request.body()
    try:
        json_data = await request.json() if raw_body else {}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Malformed JSON body: {exc}",
        )

    try:
        payload = WebhookIngestRequest.model_validate(json_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    try:
        return await service.ingest_webhook(
            connector_id=connector_id,
            raw_body=raw_body,
            headers=dict(request.headers),
            payload=payload,
        )
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConnectorDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidConnectorOperationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except WebhookAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post(
    "/{connector_id}/collect",
    status_code=status.HTTP_200_OK,
    summary="Trigger immediate poll collection",
)
async def collect_connector(
    connector_id: str,
    service: ConnectorService = Depends(get_connector_service),
) -> Dict[str, Any]:
    """Execute an immediate collection poll for an HTTP poller connector."""
    try:
        return await service.collect_connector(connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidConnectorOperationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/{connector_id}/test",
    status_code=status.HTTP_200_OK,
    summary="Test connector connectivity",
)
async def test_connector(
    connector_id: str,
    service: ConnectorService = Depends(get_connector_service),
) -> Dict[str, Any]:
    """Execute a non-mutating connectivity test without updating health state."""
    try:
        return await service.test_connector(connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
