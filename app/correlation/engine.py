"""Correlation engine for SentinelOps telemetry streams and incident evidence bundles."""

from collections import deque
from datetime import datetime, timedelta, timezone
import logging
from typing import Dict, List, Optional, Set, Tuple
import uuid

from app.common.config import config
from app.correlation.models import ActiveIncidentCorrelation, CorrelationType
from app.detection.models import DetectionAction, DetectionResult, RuleMatch
from app.incidents.models import IncidentStatus
from app.incidents.schemas import IncidentCreateRequest
from app.incidents.service import IncidentNotFoundError, IncidentService
from app.telemetry.models import Evidence, EvidenceType
from app.telemetry.repository import EvidenceRepository
from app.watcher.buffer import RollingTelemetryBuffer
from app.watcher.models import SignalType, TelemetryEvent

logger = logging.getLogger("sentinelops.correlation.engine")


class CorrelationEngine:
    """Deterministically correlates related telemetry signals into unified incident evidence bundles."""

    def __init__(
        self,
        incident_service: IncidentService,
        evidence_repository: EvidenceRepository,
        buffer: Optional[RollingTelemetryBuffer] = None,
    ) -> None:
        self._incident_service = incident_service
        self._evidence_repository = evidence_repository
        self._buffer = buffer

        # In-memory correlation state (process-lifetime only)
        # Strong request key: (project_id, service, environment, request_id) -> correlation_id
        self._strong_request_index: Dict[Tuple[str, str, str, str], str] = {}
        # Strong trace key: (project_id, service, environment, trace_id) -> correlation_id
        self._strong_trace_index: Dict[Tuple[str, str, str, str], str] = {}
        # Active correlation records: correlation_id -> ActiveIncidentCorrelation
        self._active_correlations: Dict[str, ActiveIncidentCorrelation] = {}

        # Stage 11 duplicate suppression table: fingerprint -> incident_id
        self._active_fingerprints: Dict[str, str] = {}

        # Operational metrics
        self._evaluations_count: int = 0
        self._incidents_created_count: int = 0
        self._correlated_events_count: int = 0
        self._suppressions_count: int = 0
        self._errors_count: int = 0

    @property
    def active_correlations(self) -> Dict[str, ActiveIncidentCorrelation]:
        """Return active correlation records mapped by correlation_id."""
        return dict(self._active_correlations)

    @property
    def active_fingerprints(self) -> Dict[str, str]:
        """Return active suppression fingerprints mapped to incident IDs."""
        return dict(self._active_fingerprints)

    def get_metrics(self) -> Dict[str, int]:
        """Return diagnostic metrics for the correlation engine."""
        return {
            "evaluations_count": self._evaluations_count,
            "incidents_created_count": self._incidents_created_count,
            "correlated_events_count": self._correlated_events_count,
            "suppressions_count": self._suppressions_count,
            "errors_count": self._errors_count,
            "active_correlations_count": len(self._active_correlations),
            "active_fingerprints_count": len(self._active_fingerprints),
        }

    def clear(self) -> None:
        """Reset internal correlation state. Strictly reserved for test isolation."""
        self._strong_request_index.clear()
        self._strong_trace_index.clear()
        self._active_correlations.clear()
        self._active_fingerprints.clear()
        self._evaluations_count = 0
        self._incidents_created_count = 0
        self._correlated_events_count = 0
        self._suppressions_count = 0
        self._errors_count = 0

    def set_buffer(self, buffer: RollingTelemetryBuffer) -> None:
        """Set or update the rolling buffer reference."""
        self._buffer = buffer

    def _prune_expired_correlations(self, now_process: datetime) -> None:
        """Prune active correlation records whose post-trigger collection window has elapsed."""
        expired_ids = [
            cid
            for cid, rec in self._active_correlations.items()
            if rec.is_expired(now_process)
        ]
        for cid in expired_ids:
            self._remove_correlation(cid)

    def _remove_correlation(self, correlation_id: str) -> None:
        """Remove a correlation record and clear its strong index mappings."""
        record = self._active_correlations.pop(correlation_id, None)
        if not record:
            return

        for req_id in record.request_ids:
            self._strong_request_index.pop(
                (record.project_id, record.service, record.environment, req_id), None
            )

        for trace_id in record.trace_ids:
            self._strong_trace_index.pop(
                (record.project_id, record.service, record.environment, trace_id), None
            )

    @staticmethod
    def _compute_suppression_fingerprint(event: TelemetryEvent, match: RuleMatch) -> str:
        """Compute deterministic suppression fingerprint, scoped by request_id/trace_id if present."""
        if event.request_id:
            return (
                f"{event.project_id}|{event.service}|{event.environment}|"
                f"{event.request_id}|{match.rule_id}|{match.failure_signature}"
            )
        elif event.trace_id:
            return (
                f"{event.project_id}|{event.service}|{event.environment}|"
                f"{event.trace_id}|{match.rule_id}|{match.failure_signature}"
            )
        else:
            return (
                f"{event.project_id}|{event.service}|{event.environment}|"
                f"{match.rule_id}|{match.failure_signature}"
            )

    def _find_active_correlation(
        self, event: TelemetryEvent, now_process: datetime, allow_fallback: bool = True
    ) -> Optional[Tuple[ActiveIncidentCorrelation, CorrelationType]]:
        """Evaluate strong and fallback correlation hierarchy against active non-expired records."""
        # Priority 1: Strong Key by request_id
        if event.request_id:
            req_key = (event.project_id, event.service, event.environment, event.request_id)
            cid = self._strong_request_index.get(req_key)
            if cid:
                rec = self._active_correlations.get(cid)
                if rec and not rec.is_expired(now_process):
                    return rec, CorrelationType.STRONG_REQUEST_ID

        # Priority 2: Strong Key by trace_id
        if event.trace_id:
            trace_key = (event.project_id, event.service, event.environment, event.trace_id)
            cid = self._strong_trace_index.get(trace_key)
            if cid:
                rec = self._active_correlations.get(cid)
                if rec and not rec.is_expired(now_process):
                    return rec, CorrelationType.STRONG_TRACE_ID

        # Priority 3: Fallback Secondary Correlation (telemetry time anchor + endpoint)
        # Only evaluated when request_id and trace_id are absent on candidate event
        if allow_fallback and not event.request_id and not event.trace_id and event.endpoint:
            for rec in self._active_correlations.values():
                if (
                    rec.project_id == event.project_id
                    and rec.service == event.service
                    and rec.environment == event.environment
                    and rec.endpoint == event.endpoint
                    and not rec.is_expired(now_process)
                ):
                    # Compare telemetry occurrence timestamp against the non-sliding anchor timestamp
                    delta_seconds = abs((event.timestamp - rec.anchor_event_timestamp).total_seconds())
                    if delta_seconds <= config.correlation_fallback_window_seconds:
                        return rec, CorrelationType.FALLBACK_ENDPOINT

        return None

    def observe(
        self, event: TelemetryEvent, match: Optional[RuleMatch]
    ) -> DetectionResult:
        """Observe a persisted TelemetryEvent with its detection match status."""
        self._evaluations_count += 1
        now_process = datetime.now(timezone.utc)

        try:
            # Prune records whose post-trigger window has expired in process time
            self._prune_expired_correlations(now_process)

            if not config.correlation_enabled:
                # If correlation is disabled, fall back to basic non-correlated handling
                return self._observe_without_correlation(event, match, now_process)

            # Case A: Normal / INFO Telemetry (match is None)
            if match is None:
                return self._observe_normal_telemetry(event, now_process)

            # Case B: Abnormal Telemetry (match is not None)
            return self._observe_abnormal_telemetry(event, match, now_process)

        except Exception as exc:
            self._errors_count += 1
            logger.error(
                "Error during correlation evaluation for event %s: %s",
                event.event_id,
                exc,
                exc_info=True,
            )
            # Failure isolation: return a safe result without breaking Watcher ingestion
            return DetectionResult(
                evaluated_at=now_process,
                event_id=event.event_id,
                project_id=event.project_id,
                matched=match is not None,
                rule_id=match.rule_id if match else None,
                action=DetectionAction.NO_MATCH,
                suppression_reason=f"Correlation error: {exc}",
            )

    def _observe_normal_telemetry(
        self, event: TelemetryEvent, now_process: datetime
    ) -> DetectionResult:
        """Process normal/INFO telemetry during active post-trigger collection windows."""
        # Normal telemetry must NEVER create an incident.
        # It attaches only when strongly correlated (request_id or trace_id) to an active incident within window.
        corr_result = self._find_active_correlation(event, now_process, allow_fallback=False)
        if not corr_result:
            return DetectionResult(
                evaluated_at=now_process,
                event_id=event.event_id,
                project_id=event.project_id,
                matched=False,
                action=DetectionAction.NO_MATCH,
            )

        record, corr_type = corr_result

        # Validate incident lifecycle status
        try:
            incident = self._incident_service.get_incident(record.incident_id)
            if incident.status not in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                self._remove_correlation(record.correlation_id)
                return DetectionResult(
                    evaluated_at=now_process,
                    event_id=event.event_id,
                    project_id=event.project_id,
                    matched=False,
                    action=DetectionAction.NO_MATCH,
                )
        except IncidentNotFoundError:
            self._remove_correlation(record.correlation_id)
            return DetectionResult(
                evaluated_at=now_process,
                event_id=event.event_id,
                project_id=event.project_id,
                matched=False,
                action=DetectionAction.NO_MATCH,
            )

        # Check total evidence cap
        if record.evidence_count >= config.correlation_max_evidence_per_incident:
            return DetectionResult(
                evaluated_at=now_process,
                event_id=event.event_id,
                project_id=event.project_id,
                matched=False,
                action=DetectionAction.NO_MATCH,
            )

        # Attach normal telemetry as contextual evidence
        evidence_type = (
            EvidenceType.HEALTH_CHECK
            if event.signal_type == SignalType.HEALTH
            else EvidenceType.RUNTIME_LOG
        )
        evidence = Evidence(
            id=str(uuid.uuid4()),
            incident_id=record.incident_id,
            type=evidence_type,
            source=f"watcher-{event.signal_type.value}",
            timestamp=event.timestamp,
            service=event.service,
            request_id=event.request_id,
            trace_id=event.trace_id,
            level=event.level,
            event=event.event_type,
            message=event.message,
            endpoint=event.endpoint,
            exception_type=event.exception_type,
            metadata={
                "triggering_event_id": event.event_id,
                "project_id": event.project_id,
                "correlation_role": "post_trigger_correlated",
                "correlation_type": corr_type.value,
                **event.metadata,
            },
            created_at=now_process,
        )

        existing_fingerprints = self._evidence_repository.get_fingerprints_for_incident(
            record.incident_id
        )
        if evidence.fingerprint() not in existing_fingerprints:
            self._evidence_repository.create(evidence)
            record.evidence_count += 1
            record.last_correlated_event_timestamp = event.timestamp
            self._correlated_events_count += 1

        return DetectionResult(
            evaluated_at=now_process,
            event_id=event.event_id,
            project_id=event.project_id,
            matched=False,
            action=DetectionAction.CORRELATED,
            incident_id=record.incident_id,
        )

    def _observe_abnormal_telemetry(
        self, event: TelemetryEvent, match: RuleMatch, now_process: datetime
    ) -> DetectionResult:
        """Process abnormal telemetry by either correlating to an active incident or creating one."""
        corr_result = self._find_active_correlation(event, now_process, allow_fallback=True)

        if corr_result:
            record, corr_type = corr_result

            # Verify active incident lifecycle status
            try:
                incident = self._incident_service.get_incident(record.incident_id)
                if incident.status in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                    # Incident is actively ongoing -> Correlate or Suppress
                    fingerprint = self._compute_suppression_fingerprint(event, match)

                    # Check if this exact symptom has already been registered for this incident
                    if (
                        fingerprint in record.suppression_fingerprints
                        or fingerprint in self._active_fingerprints
                    ):
                        self._suppressions_count += 1
                        return DetectionResult(
                            evaluated_at=now_process,
                            event_id=event.event_id,
                            project_id=event.project_id,
                            matched=True,
                            rule_id=match.rule_id,
                            action=DetectionAction.SUPPRESSED,
                            incident_id=record.incident_id,
                            suppression_reason=(
                                f"Active incident {record.incident_id} already has symptom {fingerprint}"
                            ),
                        )

                    # Distinct symptom for the same active incident (e.g., HTTP 500 after exception log)
                    record.suppression_fingerprints.add(fingerprint)
                    self._active_fingerprints[fingerprint] = record.incident_id

                    # Attach as correlated evidence if under total cap
                    if record.evidence_count < config.correlation_max_evidence_per_incident:
                        evidence_type = (
                            EvidenceType.HEALTH_CHECK
                            if event.signal_type == SignalType.HEALTH
                            else EvidenceType.RUNTIME_LOG
                        )
                        evidence = Evidence(
                            id=str(uuid.uuid4()),
                            incident_id=record.incident_id,
                            type=evidence_type,
                            source=f"watcher-{event.signal_type.value}",
                            timestamp=event.timestamp,
                            service=event.service,
                            request_id=event.request_id,
                            trace_id=event.trace_id,
                            level=event.level,
                            event=event.event_type,
                            message=event.message,
                            endpoint=event.endpoint,
                            exception_type=event.exception_type,
                            metadata={
                                "triggering_event_id": event.event_id,
                                "project_id": event.project_id,
                                "rule_id": match.rule_id,
                                "correlation_role": "post_trigger_correlated",
                                "correlation_type": corr_type.value,
                                **event.metadata,
                            },
                            created_at=now_process,
                        )
                        existing_fps = self._evidence_repository.get_fingerprints_for_incident(
                            record.incident_id
                        )
                        if evidence.fingerprint() not in existing_fps:
                            self._evidence_repository.create(evidence)
                            record.evidence_count += 1

                    record.last_correlated_event_timestamp = event.timestamp
                    self._correlated_events_count += 1

                    return DetectionResult(
                        evaluated_at=now_process,
                        event_id=event.event_id,
                        project_id=event.project_id,
                        matched=True,
                        rule_id=match.rule_id,
                        action=DetectionAction.CORRELATED,
                        incident_id=record.incident_id,
                    )
                else:
                    # Incident is RESOLVED or CLOSED -> invalidate correlation record and allow fresh incident
                    self._remove_correlation(record.correlation_id)
            except IncidentNotFoundError:
                self._remove_correlation(record.correlation_id)

        # Check duplicate suppression (scoped by request_id/trace_id if present)
        fingerprint = self._compute_suppression_fingerprint(event, match)
        existing_incident_id = self._active_fingerprints.get(fingerprint)
        if existing_incident_id:
            try:
                incident = self._incident_service.get_incident(existing_incident_id)
                if incident.status in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                    self._suppressions_count += 1
                    return DetectionResult(
                        evaluated_at=now_process,
                        event_id=event.event_id,
                        project_id=event.project_id,
                        matched=True,
                        rule_id=match.rule_id,
                        action=DetectionAction.SUPPRESSED,
                        incident_id=existing_incident_id,
                        suppression_reason=(
                            f"Active incident {existing_incident_id} already exists with status {incident.status.value}"
                        ),
                    )
                else:
                    self._active_fingerprints.pop(fingerprint, None)
            except IncidentNotFoundError:
                self._active_fingerprints.pop(fingerprint, None)

        # No correlation match and not suppressed -> Create NEW Incident
        req = IncidentCreateRequest(
            title=match.title,
            summary=match.summary,
            severity=match.severity,
            service=event.service,
            environment=event.environment,
        )
        created_incident = self._incident_service.create_incident(req)

        # Persist primary triggering evidence in reserved Slot 1
        evidence_type = (
            EvidenceType.HEALTH_CHECK
            if event.signal_type == SignalType.HEALTH
            else EvidenceType.RUNTIME_LOG
        )
        trigger_evidence = Evidence(
            id=str(uuid.uuid4()),
            incident_id=created_incident.id,
            type=evidence_type,
            source=f"watcher-{event.signal_type.value}",
            timestamp=event.timestamp,
            service=event.service,
            request_id=event.request_id,
            trace_id=event.trace_id,
            level=event.level,
            event=event.event_type,
            message=event.message,
            endpoint=event.endpoint,
            exception_type=event.exception_type,
            metadata={
                "triggering_event_id": event.event_id,
                "project_id": event.project_id,
                "rule_id": match.rule_id,
                "correlation_role": "trigger",
                **event.metadata,
            },
            created_at=now_process,
        )
        self._evidence_repository.create(trigger_evidence)

        # Harvest pre-trigger window from RollingTelemetryBuffer using remaining slots
        # Clarification 2: Remaining slots = MAX_EVIDENCE - 1 to preserve Slot 1 trigger
        remaining_slots = config.correlation_max_evidence_per_incident - 1
        attached_pre_count = self._harvest_pre_trigger_window(
            created_incident.id, event, now_process, remaining_slots
        )

        # Register ActiveIncidentCorrelation record
        # Clarification 3: expires_at uses current UTC process time, NOT event.timestamp
        correlation_id = str(uuid.uuid4())
        expires_at = now_process + timedelta(seconds=config.correlation_post_window_seconds)

        record = ActiveIncidentCorrelation(
            correlation_id=correlation_id,
            incident_id=created_incident.id,
            project_id=event.project_id,
            service=event.service,
            environment=event.environment,
            endpoint=event.endpoint,
            request_ids={event.request_id} if event.request_id else set(),
            trace_ids={event.trace_id} if event.trace_id else set(),
            anchor_event_timestamp=event.timestamp,
            last_correlated_event_timestamp=event.timestamp,
            created_process_time=now_process,
            expires_at_process_time=expires_at,
            evidence_count=1 + attached_pre_count,
            suppression_fingerprints={fingerprint},
        )
        self._active_correlations[correlation_id] = record

        # Clarification 4: Register ALL available strong lookup keys
        if event.request_id:
            self._strong_request_index[
                (event.project_id, event.service, event.environment, event.request_id)
            ] = correlation_id
        if event.trace_id:
            self._strong_trace_index[
                (event.project_id, event.service, event.environment, event.trace_id)
            ] = correlation_id

        self._active_fingerprints[fingerprint] = created_incident.id
        self._incidents_created_count += 1

        return DetectionResult(
            evaluated_at=now_process,
            event_id=event.event_id,
            project_id=event.project_id,
            matched=True,
            rule_id=match.rule_id,
            action=DetectionAction.INCIDENT_CREATED,
            incident_id=created_incident.id,
        )

    def _harvest_pre_trigger_window(
        self,
        incident_id: str,
        triggering_event: TelemetryEvent,
        now_process: datetime,
        remaining_slots: int,
    ) -> int:
        """Harvest bounded contextual evidence from the rolling buffer occurring before trigger."""
        if not self._buffer or remaining_slots <= 0:
            return 0

        start_time = triggering_event.timestamp - timedelta(
            seconds=config.correlation_pre_window_seconds
        )
        end_time = triggering_event.timestamp

        # Query recent candidate events from buffer
        candidates = self._buffer.get_recent(
            limit=50,
            service=triggering_event.service,
            project_id=triggering_event.project_id,
            start_time=start_time,
            end_time=end_time,
        )

        existing_fingerprints = self._evidence_repository.get_fingerprints_for_incident(
            incident_id
        )
        attached_count = 0

        # Iterate candidates chronologically (oldest to newest)
        for candidate in reversed(candidates):
            # Clarification 2: Explicitly exclude the primary triggering event
            if candidate.event_id == triggering_event.event_id:
                continue

            # Filtering rules for pre-trigger contextual evidence:
            is_eligible = False
            if triggering_event.request_id and candidate.request_id == triggering_event.request_id:
                is_eligible = True
            elif triggering_event.trace_id and candidate.trace_id == triggering_event.trace_id:
                is_eligible = True
            elif (
                not triggering_event.request_id
                and not triggering_event.trace_id
                and candidate.endpoint == triggering_event.endpoint
                and candidate.level in ("WARNING", "ERROR")
            ):
                is_eligible = True

            if not is_eligible:
                continue

            ev_type = (
                EvidenceType.HEALTH_CHECK
                if candidate.signal_type == SignalType.HEALTH
                else EvidenceType.RUNTIME_LOG
            )
            evidence = Evidence(
                id=str(uuid.uuid4()),
                incident_id=incident_id,
                type=ev_type,
                source=f"watcher-{candidate.signal_type.value}",
                timestamp=candidate.timestamp,
                service=candidate.service,
                request_id=candidate.request_id,
                trace_id=candidate.trace_id,
                level=candidate.level,
                event=candidate.event_type,
                message=candidate.message,
                endpoint=candidate.endpoint,
                exception_type=candidate.exception_type,
                metadata={
                    "triggering_event_id": candidate.event_id,
                    "project_id": candidate.project_id,
                    "correlation_role": "pre_trigger_context",
                    **candidate.metadata,
                },
                created_at=now_process,
            )

            if evidence.fingerprint() not in existing_fingerprints:
                self._evidence_repository.create(evidence)
                existing_fingerprints.add(evidence.fingerprint())
                attached_count += 1
                if attached_count >= remaining_slots:
                    break

        return attached_count

    def _observe_without_correlation(
        self, event: TelemetryEvent, match: Optional[RuleMatch], now_process: datetime
    ) -> DetectionResult:
        """Fallback behavior when correlation is disabled via configuration."""
        if match is None:
            return DetectionResult(
                evaluated_at=now_process,
                event_id=event.event_id,
                project_id=event.project_id,
                matched=False,
                action=DetectionAction.NO_MATCH,
            )

        fingerprint = self._compute_suppression_fingerprint(event, match)
        existing_id = self._active_fingerprints.get(fingerprint)
        if existing_id:
            try:
                incident = self._incident_service.get_incident(existing_id)
                if incident.status in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING):
                    self._suppressions_count += 1
                    return DetectionResult(
                        evaluated_at=now_process,
                        event_id=event.event_id,
                        project_id=event.project_id,
                        matched=True,
                        rule_id=match.rule_id,
                        action=DetectionAction.SUPPRESSED,
                        incident_id=existing_id,
                    )
            except IncidentNotFoundError:
                pass

        req = IncidentCreateRequest(
            title=match.title,
            summary=match.summary,
            severity=match.severity,
            service=event.service,
            environment=event.environment,
        )
        created_incident = self._incident_service.create_incident(req)
        ev_type = (
            EvidenceType.HEALTH_CHECK
            if event.signal_type == SignalType.HEALTH
            else EvidenceType.RUNTIME_LOG
        )
        evidence = Evidence(
            id=str(uuid.uuid4()),
            incident_id=created_incident.id,
            type=ev_type,
            source=f"watcher-{event.signal_type.value}",
            timestamp=event.timestamp,
            service=event.service,
            request_id=event.request_id,
            trace_id=event.trace_id,
            level=event.level,
            event=event.event_type,
            message=event.message,
            endpoint=event.endpoint,
            exception_type=event.exception_type,
            metadata={
                "triggering_event_id": event.event_id,
                "project_id": event.project_id,
                "rule_id": match.rule_id,
                **event.metadata,
            },
            created_at=now_process,
        )
        self._evidence_repository.create(evidence)
        self._active_fingerprints[fingerprint] = created_incident.id
        self._incidents_created_count += 1

        return DetectionResult(
            evaluated_at=now_process,
            event_id=event.event_id,
            project_id=event.project_id,
            matched=True,
            rule_id=match.rule_id,
            action=DetectionAction.INCIDENT_CREATED,
            incident_id=created_incident.id,
        )
