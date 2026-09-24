"""FastAPI dependency injection providers for SentinelOps remediation."""

from fastapi import Depends

from app.agents.dependencies import get_investigation_service
from app.agents.service import InvestigationService
from app.common.config import config
from app.incidents.dependencies import get_incident_service
from app.incidents.service import IncidentService
from app.remediation.branch_repository import (
    InMemoryRemediationBranchRepository,
    RemediationBranchRepository,
)
from app.remediation.llm import (
    FakeRemediationLLM,
    LangChainRemediationLLM,
    RemediationLLM,
)
from app.remediation.repository import (
    InMemoryRemediationRepository,
    RemediationRepository,
)
from app.remediation.review_repository import (
    InMemoryRemediationReviewRepository,
    RemediationReviewRepository,
)
from app.remediation.review_service import RemediationReviewService
from app.remediation.service import RemediationService
from app.remediation.validator import RemediationValidator
from app.repository.branch_manager import GitBranchManager
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.repository import EvidenceRepository

_shared_repository = InMemoryRemediationRepository()
_shared_review_repository = InMemoryRemediationReviewRepository()
_shared_branch_repository = InMemoryRemediationBranchRepository()
_shared_branch_manager = GitBranchManager(
    repository_path=config.git_branch_repository_path,
    base_branch=config.git_base_branch,
)
_shared_fake_llm = FakeRemediationLLM()
_shared_validator = RemediationValidator()


def get_remediation_repository() -> RemediationRepository:
    """Provides the shared in-memory remediation repository."""
    return _shared_repository


def get_review_repository() -> RemediationReviewRepository:
    """Provides the shared in-memory remediation review repository."""
    return _shared_review_repository


def get_branch_repository() -> RemediationBranchRepository:
    """Provides the shared in-memory remediation branch repository."""
    return _shared_branch_repository


def get_git_branch_manager() -> GitBranchManager:
    """Provides the GitBranchManager configured for Stage 9."""
    return _shared_branch_manager


def get_remediation_validator() -> RemediationValidator:
    """Provides the deterministic remediation validator."""
    return _shared_validator


def get_remediation_llm() -> RemediationLLM:
    """Provides configured RemediationLLM provider (offline fake or OpenAI)."""
    if config.llm_provider == "openai":
        if not config.openai_api_key:
            raise RuntimeError("OpenAI provider configured (LLM_PROVIDER=openai) but OPENAI_API_KEY is not set.")
        return LangChainRemediationLLM(
            model_name=config.llm_model,
            api_key=config.openai_api_key,
        )
    return _shared_fake_llm


def get_remediation_service(
    repository: RemediationRepository = Depends(get_remediation_repository),
    incident_service: IncidentService = Depends(get_incident_service),
    investigation_service: InvestigationService = Depends(get_investigation_service),
    evidence_repository: EvidenceRepository = Depends(get_evidence_repository),
    llm: RemediationLLM = Depends(get_remediation_llm),
    validator: RemediationValidator = Depends(get_remediation_validator),
) -> RemediationService:
    """Provides fully wired RemediationService."""
    return RemediationService(
        remediation_repository=repository,
        incident_service=incident_service,
        investigation_service=investigation_service,
        evidence_repository=evidence_repository,
        llm=llm,
        validator=validator,
    )


def get_review_service(
    remediation_repository: RemediationRepository = Depends(get_remediation_repository),
    review_repository: RemediationReviewRepository = Depends(get_review_repository),
    branch_repository: RemediationBranchRepository = Depends(get_branch_repository),
    incident_service: IncidentService = Depends(get_incident_service),
    investigation_service: InvestigationService = Depends(get_investigation_service),
    git_branch_manager: GitBranchManager = Depends(get_git_branch_manager),
) -> RemediationReviewService:
    """Provides fully wired RemediationReviewService."""
    return RemediationReviewService(
        remediation_repository=remediation_repository,
        review_repository=review_repository,
        branch_repository=branch_repository,
        incident_service=incident_service,
        investigation_service=investigation_service,
        git_branch_manager=git_branch_manager,
    )


def reset_remediation_repository() -> None:
    """Clears in-memory remediation storage (used for isolated tests)."""
    if isinstance(_shared_repository, InMemoryRemediationRepository):
        _shared_repository.clear()


def reset_review_repository() -> None:
    """Clears in-memory review storage (used for isolated tests)."""
    if isinstance(_shared_review_repository, InMemoryRemediationReviewRepository):
        _shared_review_repository.clear()


def reset_branch_repository() -> None:
    """Clears in-memory branch storage (used for isolated tests)."""
    if isinstance(_shared_branch_repository, InMemoryRemediationBranchRepository):
        _shared_branch_repository.clear()
