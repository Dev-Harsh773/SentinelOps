"""Detection engine for evaluating telemetry events against deterministic detection rules."""

from __future__ import annotations

import collections
from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING, Dict, List, Optional

from app.common.config import config
from app.detection.models import DetectionAction, DetectionResult, RuleMatch
from app.detection.rules import AppErrorRule, DetectionRule, HealthCheckFailureRule, Http5xxRule
from app.incidents.service import IncidentService
from app.telemetry.repository import EvidenceRepository
from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.models import TelemetryEvent

if TYPE_CHECKING:
    from app.correlation.engine import CorrelationEngine

logger = logging.getLogger("sentinelops.detection.engine")


class DetectionEngine:
    """Evaluates telemetry events against deterministic rules and coordinates correlation."""

    def __init__(
        self,
        incident_service: IncidentService,
        evidence_repository: EvidenceRepository,
        rules: Optional[List[DetectionRule]] = None,
        correlation_engine: Optional["CorrelationEngine"] = None,
        buffer: Optional[RollingTelemetryBuffer] = None,
    ) -> None:
        self._incident_service = incident_service
        self._evidence_repository = evidence_repository
        self._rules = (
            rules
            if rules is not None
            else [
                HealthCheckFailureRule(),
                AppErrorRule(),
                Http5xxRule(),
            ]
        )
        if correlation_engine is not None:
            self._correlation_engine = correlation_engine
        else:
            from app.correlation.engine import CorrelationEngine

            self._correlation_engine = CorrelationEngine(
                incident_service=incident_service,
                evidence_repository=evidence_repository,
                buffer=buffer,
            )
        self._recent_results: collections.deque[DetectionResult] = collections.deque(maxlen=100)

        # Operational metrics
        self._evaluations_count: int = 0
        self._matches_count: int = 0
        self._errors_count: int = 0

    @property
    def rules(self) -> List[DetectionRule]:
        """Configured detection rules in evaluation priority order."""
        return list(self._rules)

    @property
    def correlation_engine(self) -> CorrelationEngine:
        """The underlying correlation engine."""
        return self._correlation_engine

    @property
    def active_fingerprints(self) -> Dict[str, str]:
        """Mapping of active incident fingerprints to their incident IDs."""
        return self._correlation_engine.active_fingerprints

    @property
    def recent_results(self) -> List[DetectionResult]:
        """Recent bounded detection evaluation results."""
        return list(self._recent_results)

    def get_metrics(self) -> Dict[str, int]:
        """Return diagnostic metrics for the detection and correlation subsystem."""
        corr_metrics = self._correlation_engine.get_metrics()
        return {
            "evaluations_count": self._evaluations_count,
            "matches_count": self._matches_count,
            "incidents_created_count": corr_metrics["incidents_created_count"],
            "correlated_events_count": corr_metrics["correlated_events_count"],
            "suppressions_count": corr_metrics["suppressions_count"],
            "errors_count": self._errors_count + corr_metrics["errors_count"],
            "active_fingerprints_count": corr_metrics["active_fingerprints_count"],
            "active_correlations_count": corr_metrics["active_correlations_count"],
        }

    def clear(self) -> None:
        """Reset internal state. Reserved strictly for test isolation."""
        self._recent_results.clear()
        self._evaluations_count = 0
        self._matches_count = 0
        self._errors_count = 0
        self._correlation_engine.clear()

    def evaluate_rules(self, event: TelemetryEvent) -> Optional[RuleMatch]:
        """Evaluate event against deterministic rules in priority order."""
        for rule in self._rules:
            match = rule.evaluate(event)
            if match is not None:
                return match
        return None

    def evaluate(self, event: TelemetryEvent) -> DetectionResult:
        """Evaluate a single TelemetryEvent through deterministic rules and correlation."""
        if not config.detection_enabled:
            result = DetectionResult(
                evaluated_at=datetime.now(timezone.utc),
                event_id=event.event_id,
                project_id=event.project_id,
                matched=False,
                action=DetectionAction.NO_MATCH,
            )
            return result

        self._evaluations_count += 1

        try:
            # Step 1: Evaluate deterministic rules exactly once
            matched_rule = self.evaluate_rules(event)
            if matched_rule is not None:
                self._matches_count += 1

            # Step 2: Exactly one CorrelationEngine invocation per event (Clarification 1)
            result = self._correlation_engine.observe(event, matched_rule)
            self._recent_results.append(result)
            return result

        except Exception as exc:
            self._errors_count += 1
            logger.error(
                "Error during detection evaluation for event %s: %s",
                event.event_id,
                exc,
                exc_info=True,
            )
            raise
