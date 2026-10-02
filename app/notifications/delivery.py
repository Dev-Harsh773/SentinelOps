"""Background asynchronous delivery worker for notification webhooks."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from app.notifications.models import (
    DeliveryStatus,
    Notification,
    SubscriptionTestResponse,
    sanitize_webhook_recipient,
)
from app.notifications.store import SqliteNotificationStore

logger = logging.getLogger("sentinelops.notifications.delivery")

RESERVED_HEADERS = {
    "x-sentinelops-notification-id",
    "x-sentinelops-event-type",
    "x-sentinelops-delivery-attempt",
    "x-sentinelops-signature",
}


class NotificationDeliveryRuntime:
    """Manages the in-process async worker pool, backoff retries, and crash recovery."""

    def __init__(
        self,
        store: SqliteNotificationStore,
        max_concurrency: int = 5,
        poll_interval_seconds: float = 1.0,
        base_backoff_seconds: float = 2.0,
    ) -> None:
        self._store = store
        self._max_concurrency = max_concurrency
        self._poll_interval = poll_interval_seconds
        self._base_backoff = base_backoff_seconds

        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._wake_event = asyncio.Event()
        self._is_running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._poller_task: Optional[asyncio.Task] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._active_tasks: set[asyncio.Task] = set()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def wake(self) -> None:
        """Thread-safely trigger the wake event for immediate dispatch."""
        if self._is_running and self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._wake_event.set)

    async def start(self) -> None:
        """Start delivery runtime, perform crash recovery, and launch poller loop."""
        if self._is_running:
            return

        self._is_running = True
        self._loop = asyncio.get_running_loop()
        self._http_client = httpx.AsyncClient(timeout=15.0)

        # 1. Crash recovery: recover interrupted delivering tasks
        now = datetime.now(timezone.utc)
        recovered_count = self._store.recover_in_flight_on_startup(now)
        if recovered_count > 0:
            logger.info("Recovered %d interrupted notification(s) on startup", recovered_count)

        # 2. Launch background poller loop
        self._poller_task = asyncio.create_task(self._poller_loop())
        logger.info(
            "NotificationDeliveryRuntime started (concurrency=%d, poll=%.1fs)",
            self._max_concurrency,
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Cancel poller and wait for active delivery tasks to complete."""
        if not self._is_running:
            return

        self._is_running = False
        self._wake_event.set()

        if self._poller_task:
            self._poller_task.cancel()
            try:
                await self._poller_task
            except asyncio.CancelledError:
                pass

        if self._active_tasks:
            # Wait for in-flight delivery tasks with timeout
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        logger.info("NotificationDeliveryRuntime stopped cleanly")

    async def _poller_loop(self) -> None:
        """Continuously discover due pending work and dispatch worker tasks."""
        while self._is_running:
            try:
                # 1. Claim up to max_concurrency due notifications
                now = datetime.now(timezone.utc)
                due_notifications = self._store.claim_due_notifications(limit=self._max_concurrency, now=now)

                for notif in due_notifications:
                    task = asyncio.create_task(self._dispatch_with_semaphore(notif))
                    self._active_tasks.add(task)
                    task.add_done_callback(self._active_tasks.discard)

                # 2. Sleep until next poll interval or wake signal
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=self._poll_interval)
                    self._wake_event.clear()
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in notification poller loop: %s", exc, exc_info=True)
                await asyncio.sleep(self._poll_interval)

    async def _dispatch_with_semaphore(self, notif: Notification) -> None:
        """Execute single webhook delivery within concurrency semaphore."""
        async with self._semaphore:
            await self._deliver_webhook(notif)

    async def _deliver_webhook(self, notif: Notification) -> None:
        """Execute HTTP POST dispatch for a claimed notification."""
        config = notif.delivery_config or {}
        raw_url = config.get("url")
        auth_secret = config.get("auth_secret")
        custom_headers = config.get("headers", {})
        timeout_seconds = float(config.get("timeout_seconds", 10.0))

        now = datetime.now(timezone.utc)

        # 1. Validate configuration before dispatch
        if not raw_url or not (raw_url.startswith("http://") or raw_url.startswith("https://")):
            self._store.update_delivery_outcome(
                notification_id=notif.notification_id,
                delivery_status=DeliveryStatus.FAILED,
                next_attempt_at=None,
                failure_reason=f"Invalid webhook URL scheme: {raw_url}",
                now=now,
            )
            return

        # 2. Build serialized payload bytes and compute HMAC
        payload_data = {
            "notification_id": notif.notification_id,
            "project_id": notif.project_id,
            "incident_id": notif.incident_id,
            "notification_type": notif.notification_type.value,
            "severity": notif.severity.value,
            "title": notif.title,
            "summary": notif.message,
            "service": notif.payload.get("service", "unknown"),
            "environment": notif.payload.get("environment", "unknown"),
            "incident_status": notif.payload.get("incident_status", "unknown"),
            "created_at": notif.created_at.isoformat(),
            "references": notif.payload.get("references", {}),
        }
        body_bytes = json.dumps(payload_data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        # 3. Merge headers deterministically
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SentinelOps-Notifier/1.0",
        }
        for k, v in custom_headers.items():
            if k.lower() not in RESERVED_HEADERS:
                headers[k] = v

        # System reserved headers take absolute precedence
        headers["X-SentinelOps-Notification-Id"] = notif.notification_id
        headers["X-SentinelOps-Event-Type"] = notif.notification_type.value
        headers["X-SentinelOps-Delivery-Attempt"] = str(notif.attempt_count)

        if auth_secret:
            signature = hmac.new(auth_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            headers["X-SentinelOps-Signature"] = f"sha256={signature}"

        # 4. Dispatch HTTP POST
        client = self._http_client or httpx.AsyncClient(timeout=timeout_seconds)
        try:
            response = await client.post(
                raw_url,
                content=body_bytes,
                headers=headers,
                timeout=timeout_seconds,
            )
            status_code = response.status_code

            if 200 <= status_code < 300:
                # Success
                self._store.update_delivery_outcome(
                    notification_id=notif.notification_id,
                    delivery_status=DeliveryStatus.DELIVERED,
                    next_attempt_at=None,
                    failure_reason=None,
                    delivered_at=now,
                    now=now,
                )
                logger.info(
                    "Notification %s delivered successfully to %s (HTTP %d, attempt %d)",
                    notif.notification_id,
                    notif.recipient,
                    status_code,
                    notif.attempt_count,
                )
                return

            # Non-2xx response handling
            is_retryable = status_code in (408, 429) or (500 <= status_code <= 599)
            error_reason = f"HTTP {status_code}: {response.text[:200]}"
            self._handle_failure(notif, is_retryable=is_retryable, error_reason=error_reason, now=now)

        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RequestError) as exc:
            # Transport network failure is retryable
            error_reason = f"Network transport error: {type(exc).__name__}: {str(exc)[:200]}"
            self._handle_failure(notif, is_retryable=True, error_reason=error_reason, now=now)
        except Exception as exc:
            # Unexpected exception
            error_reason = f"Unexpected client error: {type(exc).__name__}: {str(exc)[:200]}"
            self._handle_failure(notif, is_retryable=False, error_reason=error_reason, now=now)

    def _handle_failure(self, notif: Notification, is_retryable: bool, error_reason: str, now: datetime) -> None:
        """Handle delivery failure, evaluate retry policy, and update SQLite state."""
        max_attempts = 3
        if is_retryable and notif.attempt_count < max_attempts:
            # Calculate backoff delay: 2.0 * (2 ** (attempt - 1))
            delay_seconds = min(self._base_backoff * (2 ** (notif.attempt_count - 1)), 60.0)
            next_attempt_at = now + timedelta(seconds=delay_seconds)
            self._store.update_delivery_outcome(
                notification_id=notif.notification_id,
                delivery_status=DeliveryStatus.PENDING,
                next_attempt_at=next_attempt_at,
                failure_reason=error_reason,
                now=now,
            )
            logger.warning(
                "Notification %s attempt %d failed (retryable): %s. Next attempt in %.1fs",
                notif.notification_id,
                notif.attempt_count,
                error_reason,
                delay_seconds,
            )
        else:
            # Terminal failure or attempts exhausted
            self._store.update_delivery_outcome(
                notification_id=notif.notification_id,
                delivery_status=DeliveryStatus.FAILED,
                next_attempt_at=None,
                failure_reason=error_reason,
                now=now,
            )
            logger.error(
                "Notification %s attempt %d failed permanently: %s",
                notif.notification_id,
                notif.attempt_count,
                error_reason,
            )

    async def send_diagnostic_ping(
        self,
        url: str,
        auth_secret: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout_seconds: float = 10.0,
        subscription_enabled: bool = True,
    ) -> SubscriptionTestResponse:
        """Execute a single diagnostic HTTP request without writing notification history."""
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return SubscriptionTestResponse(
                success=False,
                latency_ms=0.0,
                error="Invalid webhook URL scheme: must start with http:// or https://",
                subscription_enabled=subscription_enabled,
            )

        payload_data = {
            "diagnostic": True,
            "event": "sentinelops.test_ping",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "SentinelOps notification destination diagnostic check",
        }
        body_bytes = json.dumps(payload_data, separators=(",", ":")).encode("utf-8")

        req_headers = {
            "Content-Type": "application/json",
            "User-Agent": "SentinelOps-Notifier/1.0",
            "X-SentinelOps-Diagnostic": "true",
        }
        if headers:
            for k, v in headers.items():
                if k.lower() not in RESERVED_HEADERS:
                    req_headers[k] = v

        if auth_secret:
            signature = hmac.new(auth_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            req_headers["X-SentinelOps-Signature"] = f"sha256={signature}"

        start_time = time.perf_counter()
        client = self._http_client or httpx.AsyncClient(timeout=timeout_seconds)
        try:
            resp = await client.post(url, content=body_bytes, headers=req_headers, timeout=timeout_seconds)
            latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            success = 200 <= resp.status_code < 300
            return SubscriptionTestResponse(
                success=success,
                status_code=resp.status_code,
                latency_ms=latency_ms,
                error=None if success else f"HTTP {resp.status_code}: {resp.text[:200]}",
                subscription_enabled=subscription_enabled,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return SubscriptionTestResponse(
                success=False,
                status_code=None,
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
                subscription_enabled=subscription_enabled,
            )
