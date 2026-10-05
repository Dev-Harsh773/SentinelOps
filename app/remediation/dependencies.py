import threading
from typing import Optional
from fastapi import Depends

from app.agents.dependencies import get_investigation_service
from app.agents.service import InvestigationService
from app.common.config import config
from app.incidents.dependencies import get_incident_service
from app.incidents.service import IncidentService
from app.remediation.branch_repository import (
    InMemoryRemediationBranchRepository,
    RemediationBranchRepository,
    SqliteRemediationBranchRepository,
)
from app.remediation.llm import (
    FakeRemediationLLM,
    LangChainRemediationLLM,
    RemediationLLM,
)
from app.remediation.repository import (
    InMemoryRemediationRepository,
    RemediationRepository,
    SqliteRemediationRepository,
)
from app.remediation.review_repository import (
    InMemoryRemediationReviewRepository,
    RemediationReviewRepository,
    SqliteRemediationReviewRepository,
)
from app.remediation.review_service import RemediationReviewService
from app.remediation.service import RemediationService
from app.remediation.validator import RemediationValidator
from app.repository.branch_manager import GitBranchManager
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.repository import EvidenceRepository

_lock = threading.RLock()
_remediation_repository: Optional[RemediationRepository] = None
_review_repository: Optional[RemediationReviewRepository] = None
_branch_repository: Optional[RemediationBranchRepository] = None
_custom_remediation_db_path: Optional[str] = None

_shared_branch_manager = GitBranchManager(
    repository_path=config.git_branch_repository_path,
    base_branch=config.git_base_branch,
)
_shared_fake_llm = FakeRemediationLLM()
_shared_validator = RemediationValidator()


def set_custom_remediation_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect remediation stores to custom DB path (used by test suites)."""
    global _custom_remediation_db_path, _remediation_repository, _review_repository, _branch_repository
    with _lock:
        _custom_remediation_db_path = db_path
        if _remediation_repository is not None and isinstance(_remediation_repository, SqliteRemediationRepository):
            _remediation_repository.close()
        _remediation_repository = None
        if _review_repository is not None and isinstance(_review_repository, SqliteRemediationReviewRepository):
            _review_repository.close()
        _review_repository = None
        if _branch_repository is not None and isinstance(_branch_repository, SqliteRemediationBranchRepository):
            _branch_repository.close()
        _branch_repository = None


def get_remediation_repository(db_path: Optional[str] = None) -> RemediationRepository:
    """Provides the shared remediation repository."""
    global _remediation_repository
    with _lock:
        if _remediation_repository is None:
            resolved_db = db_path or _custom_remediation_db_path or "runtime/sentinelops.db"
            _remediation_repository = SqliteRemediationRepository(db_path=resolved_db)
        return _remediation_repository


def get_review_repository(db_path: Optional[str] = None) -> RemediationReviewRepository:
    """Provides the shared remediation review repository."""
    global _review_repository
    with _lock:
        if _review_repository is None:
            resolved_db = db_path or _custom_remediation_db_path or "runtime/sentinelops.db"
            _review_repository = SqliteRemediationReviewRepository(db_path=resolved_db)
        return _review_repository


def get_branch_repository(db_path: Optional[str] = None) -> RemediationBranchRepository:
    """Provides the shared remediation branch repository."""
    global _branch_repository
    with _lock:
        if _branch_repository is None:
            resolved_db = db_path or _custom_remediation_db_path or "runtime/sentinelops.db"
            _branch_repository = SqliteRemediationBranchRepository(db_path=resolved_db)
        return _branch_repository


def close_remediation_repositories() -> None:
    """Closes all remediation repository singletons."""
    global _remediation_repository, _review_repository, _branch_repository
    with _lock:
        if _remediation_repository is not None and isinstance(_remediation_repository, SqliteRemediationRepository):
            _remediation_repository.close()
        _remediation_repository = None
        if _review_repository is not None and isinstance(_review_repository, SqliteRemediationReviewRepository):
            _review_repository.close()
        _review_repository = None
        if _branch_repository is not None and isinstance(_branch_repository, SqliteRemediationBranchRepository):
            _branch_repository.close()
        _branch_repository = None



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
    """Clears remediation storage (used for isolated tests)."""
    repo = get_remediation_repository()
    if repo:
        repo.clear()


def reset_review_repository() -> None:
    """Clears review storage (used for isolated tests)."""
    repo = get_review_repository()
    if repo:
        repo.clear()


def reset_branch_repository() -> None:
    """Clears branch storage (used for isolated tests)."""
    repo = get_branch_repository()
    if repo:
        repo.clear()
