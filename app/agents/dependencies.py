"""Dependency injection providers for SentinelOps AI incident investigation."""

from fastapi import Depends

from app.agents.llm import (
    FakeInvestigationLLM,
    InvestigationLLM,
    LangChainInvestigationLLM,
)
import threading
from typing import Optional

from app.agents.models import InvestigationLLMError
from app.agents.repository import (
    InMemoryInvestigationRepository,
    InvestigationRepository,
    SqliteInvestigationRepository,
)
from app.agents.service import InvestigationService
from app.common.config import config
from app.incidents.dependencies import get_incident_service
from app.incidents.service import IncidentService
from app.knowledge.dependencies import get_project_knowledge_service
from app.knowledge.service import ProjectKnowledgeService
from app.memory.dependencies import get_memory_service
from app.memory.service import IncidentMemoryService
from app.repository.dependencies import get_git_service
from app.repository.service import GitService
from app.retrieval.dependencies import get_retrieval_service
from app.retrieval.service import RetrievalService
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.repository import EvidenceRepository

_lock = threading.RLock()
_investigation_repository: Optional[InvestigationRepository] = None
_custom_investigation_db_path: Optional[str] = None
_shared_fake_llm = FakeInvestigationLLM()


def set_custom_investigation_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect investigation store to custom DB path (used by test suites)."""
    global _custom_investigation_db_path, _investigation_repository
    with _lock:
        _custom_investigation_db_path = db_path
        if _investigation_repository is not None and isinstance(_investigation_repository, SqliteInvestigationRepository):
            _investigation_repository.close()
        _investigation_repository = None


def get_investigation_repository(db_path: Optional[str] = None) -> InvestigationRepository:
    """Provides the shared InvestigationRepository instance."""
    global _investigation_repository
    with _lock:
        if _investigation_repository is None:
            resolved_db = db_path or _custom_investigation_db_path or "runtime/sentinelops.db"
            _investigation_repository = SqliteInvestigationRepository(db_path=resolved_db)
        return _investigation_repository


def close_investigation_repository() -> None:
    """Closes the investigation repository singleton."""
    global _investigation_repository
    with _lock:
        if _investigation_repository is not None and isinstance(_investigation_repository, SqliteInvestigationRepository):
            _investigation_repository.close()
        _investigation_repository = None



def get_investigation_llm() -> InvestigationLLM:
    """Provides the configured InvestigationLLM implementation."""
    if config.llm_provider == "openai":
        if not config.openai_api_key:
            raise InvestigationLLMError(
                "OpenAI provider configured (LLM_PROVIDER=openai) but OPENAI_API_KEY is not set."
            )
        return LangChainInvestigationLLM(
            model_name=config.llm_model,
            api_key=config.openai_api_key,
        )
    return _shared_fake_llm


def get_investigation_service(
    investigation_repository: InvestigationRepository = Depends(get_investigation_repository),
    incident_service: IncidentService = Depends(get_incident_service),
    evidence_repository: EvidenceRepository = Depends(get_evidence_repository),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    git_service: GitService = Depends(get_git_service),
    llm: InvestigationLLM = Depends(get_investigation_llm),
    memory_service: IncidentMemoryService = Depends(get_memory_service),
    knowledge_service: ProjectKnowledgeService = Depends(get_project_knowledge_service),
) -> InvestigationService:
    """Provides a fully wired InvestigationService."""
    return InvestigationService(
        investigation_repository=investigation_repository,
        incident_service=incident_service,
        evidence_repository=evidence_repository,
        retrieval_service=retrieval_service,
        git_service=git_service,
        llm=llm,
        git_limit=config.git_context_limit,
        max_revisions=config.rca_max_revisions,
        memory_service=memory_service,
        knowledge_service=knowledge_service,
    )
