"""FastAPI routes for Incident Memory inspection and search."""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.memory.dependencies import get_memory_service
from app.memory.models import (
    HistoricalIncidentContextSchema,
    HistoricalSearchQuery,
    IncidentMemoryResponseSchema,
    MemorySearchRequestSchema,
    MemorySearchResponseSchema,
)
from app.memory.service import IncidentMemoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["Memory"])


@router.get("", response_model=List[IncidentMemoryResponseSchema])
def list_incident_memories(
    service: IncidentMemoryService = Depends(get_memory_service),
) -> List[IncidentMemoryResponseSchema]:
    """Retrieve all stored trusted incident memories."""
    memories = service.list_memories()
    return [
        IncidentMemoryResponseSchema(
            incident_id=m.incident_id,
            service=m.service,
            environment=m.environment,
            title=m.title,
            failure_location=m.failure_location,
            triggering_condition=m.triggering_condition,
            root_cause_hypothesis=m.root_cause_hypothesis,
            summary=m.summary,
            endpoint=m.endpoint,
            exception_type=m.exception_type,
            relevant_symbols=m.relevant_symbols,
            relevant_files=m.relevant_files,
            resolution_notes=m.resolution_notes,
            investigation_id=m.investigation_id,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in memories
    ]


@router.get("/{incident_id}", response_model=IncidentMemoryResponseSchema)
def get_incident_memory(
    incident_id: str,
    service: IncidentMemoryService = Depends(get_memory_service),
) -> IncidentMemoryResponseSchema:
    """Retrieve the trusted incident memory for a specific incident ID."""
    memory = service.get_memory(incident_id)
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No memory record found for incident '{incident_id}'.",
        )
    return IncidentMemoryResponseSchema(
        incident_id=memory.incident_id,
        service=memory.service,
        environment=memory.environment,
        title=memory.title,
        failure_location=memory.failure_location,
        triggering_condition=memory.triggering_condition,
        root_cause_hypothesis=memory.root_cause_hypothesis,
        summary=memory.summary,
        endpoint=memory.endpoint,
        exception_type=memory.exception_type,
        relevant_symbols=memory.relevant_symbols,
        relevant_files=memory.relevant_files,
        resolution_notes=memory.resolution_notes,
        investigation_id=memory.investigation_id,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


@router.post("/search", response_model=MemorySearchResponseSchema)
def search_incident_memories(
    request: MemorySearchRequestSchema,
    service: IncidentMemoryService = Depends(get_memory_service),
) -> MemorySearchResponseSchema:
    """Search historical incident memories deterministically."""
    query = HistoricalSearchQuery(
        current_incident_id=request.current_incident_id,
        service=request.service,
        environment=request.environment,
        exception_type=request.exception_type,
        endpoint=request.endpoint,
        query_text=request.query_text or "",
        relevant_symbols=request.relevant_symbols,
        relevant_files=request.relevant_files,
        limit=request.limit,
    )
    results = service.search_history(query)
    schema_results = [
        HistoricalIncidentContextSchema(
            incident_id=r.incident_id,
            title=r.title,
            service=r.service,
            failure_location=r.failure_location,
            triggering_condition=r.triggering_condition,
            root_cause_hypothesis=r.root_cause_hypothesis,
            similarity_score=r.similarity_score,
            matched_signals=r.matched_signals,
            resolution_notes=r.resolution_notes,
        )
        for r in results
    ]
    return MemorySearchResponseSchema(
        results=schema_results,
        total=len(schema_results),
    )
