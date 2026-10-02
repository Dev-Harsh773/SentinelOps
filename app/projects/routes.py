"""FastAPI routes for Project onboarding and Project Knowledge Base APIs."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.knowledge.dependencies import get_project_knowledge_service
from app.knowledge.models import ProjectKnowledgeSnapshot
from app.knowledge.service import (
    ProjectKnowledgeService,
    ProjectNotIndexedError,
    ProjectNotReadyError,
    ProjectReindexError,
    ProjectWorkspaceNotFoundError,
)
from app.projects.dependencies import get_project_service
from app.projects.schemas import ProjectRegisterRequest, ProjectResponse
from app.projects.service import (
    InvalidWorkspacePathError,
    ProjectOnboardingError,
    ProjectService,
)
from app.projects.storage import (
    DuplicateProjectIdError,
    DuplicateWorkspacePathError,
    ProjectHasActiveConnectorsError,
    ProjectNotFoundError,
)
from app.retrieval.schemas import SearchRequest, SearchResponse

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard and index a new project",
)
def register_project(
    payload: ProjectRegisterRequest,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """Register a local repository workspace and build its initial knowledge base."""
    try:
        project = service.register_project(payload)
        return ProjectResponse.model_validate(project)
    except (DuplicateProjectIdError, DuplicateWorkspacePathError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (InvalidWorkspacePathError, ProjectOnboardingError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "",
    response_model=List[ProjectResponse],
    status_code=status.HTTP_200_OK,
    summary="List all onboarded projects",
)
def list_projects(
    service: ProjectService = Depends(get_project_service),
) -> List[ProjectResponse]:
    """Retrieve all onboarded projects."""
    projects = service.list_projects()
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Get project by ID",
)
def get_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    """Retrieve details for a specific project."""
    try:
        project = service.get_project(project_id)
        return ProjectResponse.model_validate(project)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an onboarded project",
)
def delete_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> None:
    """Delete a project if no active connectors or foreign key references exist."""
    try:
        deleted = service.delete_project(project_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project '{project_id}' not found.")
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectHasActiveConnectorsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/{project_id}/reindex",
    response_model=ProjectKnowledgeSnapshot,
    status_code=status.HTTP_200_OK,
    summary="Reindex a project's workspace",
)
def reindex_project(
    project_id: str,
    knowledge_service: ProjectKnowledgeService = Depends(get_project_knowledge_service),
) -> ProjectKnowledgeSnapshot:
    """Refresh a project's knowledge base. Preserves previous good index if reindex fails."""
    try:
        return knowledge_service.reindex_project(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectReindexError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    except ProjectWorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/{project_id}/knowledge",
    response_model=ProjectKnowledgeSnapshot,
    status_code=status.HTTP_200_OK,
    summary="Get project knowledge snapshot",
)
def get_project_knowledge(
    project_id: str,
    knowledge_service: ProjectKnowledgeService = Depends(get_project_knowledge_service),
) -> ProjectKnowledgeSnapshot:
    """Retrieve the high-level knowledge snapshot for a project."""
    try:
        return knowledge_service.get_project_knowledge(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectWorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ProjectNotReadyError, ProjectNotIndexedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/{project_id}/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search source code within a project",
)
def search_project_code(
    project_id: str,
    payload: SearchRequest,
    knowledge_service: ProjectKnowledgeService = Depends(get_project_knowledge_service),
) -> SearchResponse:
    """Execute project-scoped lexical code retrieval."""
    try:
        return knowledge_service.search_code(project_id, query=payload.query, limit=payload.limit)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ProjectWorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ProjectNotReadyError, ProjectNotIndexedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
