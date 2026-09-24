"""Dependency injection providers for SentinelOps AI incident investigation."""

from fastapi import Depends

from app.agents.llm import (
    FakeInvestigationLLM,
    InvestigationLLM,
    LangChainInvestigationLLM,
)
from app.agents.repository import (
    InMemoryInvestigationRepository,
    InvestigationRepository,
)
from app.agents.service import InvestigationService
from app.common.config import config
from app.incidents.dependencies import get_incident_service
from app.incidents.service import IncidentService
from app.memory.dependencies import get_memory_service
from app.memory.service import IncidentMemoryService
from app.repository.dependencies import get_git_service
from app.repository.service import GitService
from app.retrieval.dependencies import get_retrieval_service
from app.retrieval.service import RetrievalService
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.repository import EvidenceRepository

from app.agents.models import InvestigationLLMError

# Shared singleton in-memory repository for investigation results
_shared_investigation_repository = InMemoryInvestigationRepository()

# Shared singleton for mock LLM instance when mock provider is active
_shared_fake_llm = FakeInvestigationLLM()


def get_investigation_repository() -> InvestigationRepository:
    """Provides the shared InvestigationRepository instance."""
    return _shared_investigation_repository


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
    )
