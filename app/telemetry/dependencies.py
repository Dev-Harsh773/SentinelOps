"""Dependency injection providers for Telemetry and Evidence collection."""

from fastapi import Depends

from app.common.config import config
from app.incidents.dependencies import get_incident_service
from app.incidents.service import IncidentService
from app.telemetry.collector import RuntimeLogCollector
from app.telemetry.repository import EvidenceRepository, InMemoryEvidenceRepository
from app.telemetry.service import TelemetryService

# Shared in-memory evidence repository instance across runtime requests
_shared_evidence_repository = InMemoryEvidenceRepository()


def get_evidence_repository() -> EvidenceRepository:
    """Provide the shared evidence repository instance."""
    return _shared_evidence_repository


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
