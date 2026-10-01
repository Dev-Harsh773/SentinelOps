"""Deterministic detection rules for SentinelOps runtime telemetry."""

from abc import ABC, abstractmethod
from typing import Optional

from app.detection.models import RuleMatch
from app.incidents.models import Severity
from app.watcher.models import SignalType, TelemetryEvent


class DetectionRule(ABC):
    """Abstract contract for deterministic telemetry evaluation rules."""

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique deterministic identifier for the rule."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable rule name."""
        pass

    @abstractmethod
    def evaluate(self, event: TelemetryEvent) -> Optional[RuleMatch]:
        """Evaluate a normalized TelemetryEvent; return RuleMatch if condition met."""
        pass


class HealthCheckFailureRule(DetectionRule):
    """Priority 1: Detects synthetic endpoint health probe failures."""

    @property
    def rule_id(self) -> str:
        return "rule.health_check_failed"

    @property
    def name(self) -> str:
        return "Health Check Failure Rule"

    def evaluate(self, event: TelemetryEvent) -> Optional[RuleMatch]:
        if event.signal_type != SignalType.HEALTH:
            return None

        if event.level == "ERROR" and event.event_type == "health_check_failed":
            failure_type = event.metadata.get("failure_type", "unknown")
            endpoint = event.endpoint or ""
            return RuleMatch(
                rule_id=self.rule_id,
                rule_name=self.name,
                title=f"Health Check Failed: {event.service}",
                summary=f"[Project: {event.project_id}] Health probe failed for {event.service} ({event.environment}): {event.message}.",
                severity=Severity.HIGH,
                failure_signature=f"{failure_type}|{endpoint}",
            )

        return None


class AppErrorRule(DetectionRule):
    """Priority 2: Detects application ERROR logs, exceptions, and code failures."""

    @property
    def rule_id(self) -> str:
        return "rule.app_error"

    @property
    def name(self) -> str:
        return "Application Error Rule"

    def evaluate(self, event: TelemetryEvent) -> Optional[RuleMatch]:
        if event.signal_type != SignalType.LOG:
            return None

        # Evaluates all application ERROR logs, with or without unhandled exceptions
        if event.level == "ERROR":
            err_ident = event.exception_type or event.event_type
            endpoint = event.endpoint or ""
            return RuleMatch(
                rule_id=self.rule_id,
                rule_name=self.name,
                title=f"Application Error in {event.service}: {err_ident}",
                summary=f"[Project: {event.project_id}] Application error detected in {event.service} ({event.environment}): {event.message}.",
                severity=Severity.HIGH,
                failure_signature=f"{err_ident}|{endpoint}",
            )

        return None


class Http5xxRule(DetectionRule):
    """Priority 3: Detects server-side HTTP 5xx responses without application ERROR logs."""

    @property
    def rule_id(self) -> str:
        return "rule.http_5xx"

    @property
    def name(self) -> str:
        return "HTTP 5xx Server Error Rule"

    def evaluate(self, event: TelemetryEvent) -> Optional[RuleMatch]:
        if event.signal_type not in (SignalType.LOG, SignalType.CUSTOM):
            return None

        # Matches telemetry with status_code >= 500 not already captured as ERROR logs
        if event.status_code is not None and event.status_code >= 500 and event.level != "ERROR":
            endpoint = event.endpoint or ""
            return RuleMatch(
                rule_id=self.rule_id,
                rule_name=self.name,
                title=f"HTTP {event.status_code} Error on {event.service} {endpoint}".strip(),
                summary=f"[Project: {event.project_id}] HTTP {event.status_code} server error returned on {endpoint or 'service'}: {event.message}.",
                severity=Severity.HIGH,
                failure_signature=f"{event.status_code}|{endpoint}",
            )

        return None
