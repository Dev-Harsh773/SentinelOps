"""FastAPI router exposing repository indexing, status, and code retrieval endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.retrieval.dependencies import get_retrieval_service
from app.retrieval.index import RepositoryNotIndexedError
from app.retrieval.scanner import RepositoryNotFoundError
from app.retrieval.schemas import (
    IndexStatusResponse,
    IndexSummaryResponse,
    SearchRequest,
    SearchResponse,
)
from app.retrieval.service import RetrievalService

router = APIRouter(prefix="/repository", tags=["Repository"])


@router.post(
    "/index",
    response_model=IndexSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Index repository source code",
)
def index_repository(
    service: RetrievalService = Depends(get_retrieval_service),
) -> IndexSummaryResponse:
    """Scans and indexes the configured source repository."""
    try:
        return service.index_repository()
    except RepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/status",
    response_model=IndexStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get repository indexing status",
)
def get_index_status(
    service: RetrievalService = Depends(get_retrieval_service),
) -> IndexStatusResponse:
    """Returns the current state and metadata of the repository index."""
    domain_status = service.get_status()
    return IndexStatusResponse(
        indexed=domain_status.indexed,
        files_indexed=domain_status.files_indexed,
        chunks=domain_status.chunks,
        repository=domain_status.repository,
        indexed_at=domain_status.indexed_at,
    )


@router.post(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search indexed source code chunks",
)
def search_repository(
    payload: SearchRequest,
    service: RetrievalService = Depends(get_retrieval_service),
) -> SearchResponse:
    """Searches indexed source code chunks using lexical scoring."""
    try:
        return service.search(query=payload.query, limit=payload.limit)
    except RepositoryNotIndexedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
