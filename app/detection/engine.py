"""Detection engine for evaluating telemetry events and creating incidents."""

import collections
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional
import uuid

from app.common.config import config
from app.detection.models import DetectionAction, DetectionResult, RuleMatch
from app.detection.rules import AppErrorRule, DetectionRule, HealthCheckFailureRule, Http5xxRule
from app.incidents.models import IncidentStatus
from app.incidents.schemas import IncidentCreateRequest
from app.incidents.service import IncidentNotFoundError, IncidentService
from app.telemetry.models import Evidence, EvidenceType
from app.telemetry.repository import EvidenceRepository
from app.watcher.models import SignalType, TelemetryEvent

logger = logging.getLogger("sentinelops.detection.engine")


class DetectionEngine:
    """Evaluates telemetry events against deterministic rules and manages incident creation."""

    def __init__(
        self,
        incident_service: IncidentService,
        evidence_repository: EvidenceRepository,
        rules: Optional[List[DetectionRule]] = None,
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
        self._active_fingerprints: Dict[str, str] = {}
        self._recent_results: collections.deque[DetectionResult] = collections.deque(maxlen=100)

        # Operational metrics
        self._evaluations_count: int = 0
        self._matches_count: int = 0
        self._incidents_created_count: int = 0
        self._suppressions_count: int = 0
        self._errors_count: int = 0

    @property
    def rules(self) -> List[DetectionRule]:
        """Configured detection rules in evaluation priority order."""
        return list(self._rules)

    @property
    def active_fingerprints(self) -> Dict[str, str]:
        """Mapping of active incident fingerprints to their incident IDs."""
        return dict(self._active_fingerprints)

    @property
    def recent_results(self) -> List[DetectionResult]:
        """Recent bounded detection evaluation results."""
        return list(self._recent_results)

    def get_metrics(self) -> Dict[str, int]:
        """Return diagnostic metrics for the detection engine."""
        return {
            "evaluations_count": self._evaluations_count,
            "matches_count": self._matches_count,
            "incidents_created_count": self._incidents_created_count,
            "suppressions_count": self._suppressions_count,
            "errors_count": self._errors_count,
            "active_fingerprints_count": len(self._active_fingerprints),
        }

    def clear(self) -> None:
        """Reset internal state. Reserved strictly for test isolation."""
        self._active_fingerprints.clear()
        self._recent_results.clear()
        self._evaluations_count = 0
        self._matches_count = 0
        self._incidents_created_count = 0
        self._suppressions_count = 0
        self._errors_count = 0

    def evaluate(self, event: TelemetryEvent) -> DetectionResult:
        """Evaluate a single TelemetryEvent through deterministic detection rules."""
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
            matched_rule: Optional[RuleMatch] = None
            for rule in self._rules:
                matched_rule = rule.evaluate(event)
                if matched_rule is not None:
                    break

            if matched_rule is None:
                result = DetectionResult(
                    evaluated_at=datetime.now(timezone.utc),
                    event_id=event.event_id,
                    project_id=event.project_id,
                    matched=False,
                    action=DetectionAction.NO_MATCH,
                )
                self._recent_results.append(result)
                return result

            self._matches_count += 1

            # Correction 1: Include project_id in suppression fingerprint
            fingerprint = (
                f"{event.project_id}|{event.service}|{event.environment}|"
                f"{matched_rule.rule_id}|{matched_rule.failure_signature}"
            )

            # Check duplicate suppression against active incidents
            existing_incident_id = self._active_fingerprints.get(fingerprint)
            if existing_incident_id:
                try:
                    incident = self._incident_service.get_incident(existing_incident_id)
                    if incident.status in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                        self._suppressions_count += 1
                        result = DetectionResult(
                            evaluated_at=datetime.now(timezone.utc),
                            event_id=event.event_id,
                            project_id=event.project_id,
                            matched=True,
                            rule_id=matched_rule.rule_id,
                            action=DetectionAction.SUPPRESSED,
                            incident_id=existing_incident_id,
                            suppression_reason=(
                                f"Active incident {existing_incident_id} already exists "
                                f"with status {incident.status.value}"
                            ),
                        )
                        self._recent_results.append(result)
                        return result
                    else:
                        # Incident was resolved or closed; clear fingerprint so recurrence creates new incident
                        self._active_fingerprints.pop(fingerprint, None)
                except IncidentNotFoundError:
                    self._active_fingerprints.pop(fingerprint, None)

            # Create new incident via IncidentService
            req = IncidentCreateRequest(
                title=matched_rule.title,
                summary=matched_rule.summary,
                severity=matched_rule.severity,
                service=event.service,
                environment=event.environment,
            )
            created_incident = self._incident_service.create_incident(req)

            # Determine evidence type and attach triggering telemetry to evidence repository
            evidence_type = (
                EvidenceType.HEALTH_CHECK
                if event.signal_type == SignalType.HEALTH
                else EvidenceType.RUNTIME_LOG
            )
            evidence = Evidence(
                id=str(uuid.uuid4()),
                incident_id=created_incident.id,
                type=evidence_type,
                source=f"watcher-{event.signal_type.value}",
                timestamp=event.timestamp,
                service=event.service,
                request_id=event.request_id,
                level=event.level,
                event=event.event_type,
                message=event.message,
                endpoint=event.endpoint,
                exception_type=event.exception_type,
                metadata={
                    "triggering_event_id": event.event_id,
                    "project_id": event.project_id,
                    "rule_id": matched_rule.rule_id,
                    **event.metadata,
                },
                created_at=datetime.now(timezone.utc),
            )
            self._evidence_repository.create(evidence)

            # Record active fingerprint and update metrics
            self._active_fingerprints[fingerprint] = created_incident.id
            self._incidents_created_count += 1

            result = DetectionResult(
                evaluated_at=datetime.now(timezone.utc),
                event_id=event.event_id,
                project_id=event.project_id,
                matched=True,
                rule_id=matched_rule.rule_id,
                action=DetectionAction.INCIDENT_CREATED,
                incident_id=created_incident.id,
            )
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
