"""Dependency injection providers for correlation subsystem."""

from typing import TYPE_CHECKING, Optional
from app.incidents.dependencies import get_incident_service
from app.telemetry.dependencies import get_evidence_repository

if TYPE_CHECKING:
    from app.correlation.engine import CorrelationEngine

_correlation_engine_instance: Optional["CorrelationEngine"] = None


def get_correlation_engine() -> "CorrelationEngine":
    """Provide the shared CorrelationEngine singleton instance."""
    global _correlation_engine_instance
    if _correlation_engine_instance is None:
        from app.correlation.engine import CorrelationEngine
        from app.watcher.dependencies import get_watcher_buffer

        incident_service = get_incident_service()
        evidence_repository = get_evidence_repository()
        buffer = get_watcher_buffer()

        _correlation_engine_instance = CorrelationEngine(
            incident_service=incident_service,
            evidence_repository=evidence_repository,
            buffer=buffer,
        )
    return _correlation_engine_instance


def reset_correlation_state() -> None:
    """Reset correlation engine instance for test isolation."""
    global _correlation_engine_instance
    if _correlation_engine_instance:
        _correlation_engine_instance.clear()
    _correlation_engine_instance = None
