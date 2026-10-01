"""Dependency injection providers for detection engine."""

from typing import TYPE_CHECKING, Optional
from app.incidents.dependencies import get_incident_service
from app.telemetry.dependencies import get_evidence_repository

if TYPE_CHECKING:
    from app.detection.engine import DetectionEngine

_detection_engine_instance: Optional["DetectionEngine"] = None


def get_detection_engine() -> "DetectionEngine":
    """Provide the shared DetectionEngine instance."""
    global _detection_engine_instance
    if _detection_engine_instance is None:
        from app.correlation.dependencies import get_correlation_engine
        from app.detection.engine import DetectionEngine

        incident_service = get_incident_service()
        evidence_repository = get_evidence_repository()
        correlation_engine = get_correlation_engine()
        _detection_engine_instance = DetectionEngine(
            incident_service=incident_service,
            evidence_repository=evidence_repository,
            correlation_engine=correlation_engine,
        )
    return _detection_engine_instance


def reset_detection_state() -> None:
    """Reset detection engine instance for test isolation."""
    global _detection_engine_instance
    if _detection_engine_instance:
        _detection_engine_instance.clear()
    _detection_engine_instance = None
