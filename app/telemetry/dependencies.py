"""Dependency injection providers for Telemetry and Evidence collection."""

from fastapi import Depends

from app.common.config import config
from app.incidents.dependencies import get_incident_service
from app.incidents.service import IncidentService
from app.telemetry.collector import RuntimeLogCollector
import threading
from typing import Optional

from app.telemetry.repository import EvidenceRepository, InMemoryEvidenceRepository, SqliteEvidenceRepository
from app.telemetry.service import TelemetryService

_lock = threading.RLock()
_evidence_repository: Optional[EvidenceRepository] = None
_custom_evidence_db_path: Optional[str] = None


def set_custom_evidence_db_path(db_path: Optional[str]) -> None:
    """Explicitly redirect evidence store to custom DB path (used by test suites)."""
    global _custom_evidence_db_path, _evidence_repository
    with _lock:
        _custom_evidence_db_path = db_path
        if _evidence_repository is not None and isinstance(_evidence_repository, SqliteEvidenceRepository):
            _evidence_repository.close()
        _evidence_repository = None


def get_evidence_repository(db_path: Optional[str] = None) -> EvidenceRepository:
    """Provide the shared evidence repository instance."""
    global _evidence_repository
    with _lock:
        if _evidence_repository is None:
            resolved_db = db_path or _custom_evidence_db_path or "runtime/sentinelops.db"
            _evidence_repository = SqliteEvidenceRepository(db_path=resolved_db)
        return _evidence_repository


def close_evidence_repository() -> None:
    """Closes the evidence repository singleton."""
    global _evidence_repository
    with _lock:
        if _evidence_repository is not None and isinstance(_evidence_repository, SqliteEvidenceRepository):
            _evidence_repository.close()
        _evidence_repository = None



def get_log_collector() -> RuntimeLogCollector:
    """Provide a log collector configured with the application log path."""
    return RuntimeLogCollector(log_path=config.demo_app_log_path)


def get_telemetry_service(
    incident_service: IncidentService = Depends(get_incident_service),
    evidence_repository: EvidenceRepository = Depends(get_evidence_repository),
    log_collector: RuntimeLogCollector = Depends(get_log_collector),
) -> TelemetryService:
    """Provide the telemetry service configured with incidents, evidence storage, and collector."""
    return TelemetryService(
        incident_service=incident_service,
        evidence_repository=evidence_repository,
        log_collector=log_collector,
    )
