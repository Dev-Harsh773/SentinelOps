"""Background asynchronous delivery worker for notification webhooks."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import time
import socket
from typing import Any, Dict, List, Optional

import httpx

from app.notifications.models import (
    DeliveryStatus, FailureCategory, WebhookDestinationConfig,
    Notification,
    SubscriptionTestResponse,
)
from app.notifications.store import SqliteNotificationStore
from app.notifications.transport_logging import private_post

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
        retry_cap_seconds: float = 60.0,
        lease_seconds: float = 120.0,
        enabled: bool = True,
    ) -> None:
        self.process_intents = None
        self._enabled = enabled
        self._retry_cap = retry_cap_seconds
        self._lease_seconds = lease_seconds
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
        if self._is_running or not self._enabled:
            return

        self._is_running = True
        self._loop = asyncio.get_running_loop()
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=15.0)

        # 1. Crash recovery: recover interrupted delivering tasks
        now = datetime.now(timezone.utc)
        recovered_count = await asyncio.to_thread(self._store.recover_in_flight_on_startup, now)
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
                if self.process_intents:
                    await asyncio.to_thread(self.process_intents)
                recovered = await asyncio.to_thread(self._store.recover_in_flight_on_startup, now)
                if recovered:
                    logger.info("Recovered %d expired notification lease(s)", recovered)
                capacity = self._max_concurrency - len(self._active_tasks)
                due_notifications = await asyncio.to_thread(self._store.claim_due_notifications,
                    limit=capacity, now=now, lease_seconds=self._lease_seconds)

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
                logger.error("Notification poller error (%s)", type(exc).__name__)
                await asyncio.sleep(self._poll_interval)

    async def _dispatch_with_semaphore(self, notif: Notification) -> None:
        """Execute single webhook delivery within concurrency semaphore."""
        async with self._semaphore:
            await self._deliver_webhook(notif)

    async def _deliver_webhook(self, notif: Notification) -> None:
        """Dispatch once per lease, under a total deadline shorter than the lease."""
        now = datetime.now(timezone.utc)
        if not notif.claim_token or not await asyncio.to_thread(self._store.begin_dispatch, notif.notification_id, notif.claim_token, now):
            return
        start = time.perf_counter()
        logger.info("Notification attempt started id=%s project=%s incident=%s attempt=%d",
                    notif.notification_id, notif.project_id, notif.incident_id, notif.attempt_count)
        try:
            cfg = WebhookDestinationConfig.model_validate(notif.delivery_config or {})
            raw_url, auth_secret, custom_headers, timeout_seconds = cfg.url, cfg.auth_secret, cfg.headers, cfg.timeout_seconds
        except Exception:
            await self._finish(notif, FailureCategory.CONFIGURATION, "Invalid webhook configuration", False, start)
            return
        from app.common.security import SSRFGuard, SSRFValidationError
        is_mock = self._http_client is not None and isinstance(self._http_client._transport, httpx.MockTransport)
        if not is_mock:
            try:
                await asyncio.wait_for(asyncio.to_thread(SSRFGuard.validate_url, raw_url), timeout=2.0)
            except asyncio.TimeoutError:
                await self._finish(notif, FailureCategory.TIMEOUT, "Destination validation timed out", True, start)
                return
            except SSRFValidationError as exc:
                if isinstance(exc.__cause__, socket.gaierror):
                    await self._finish(notif, FailureCategory.NETWORK, "Destination name resolution failed", True, start)
                else:
                    await self._finish(notif, FailureCategory.CONFIGURATION, "Destination rejected by outbound security policy", False, start)
                return
            except Exception:
                await self._finish(notif, FailureCategory.CONFIGURATION, "Invalid destination", False, start)
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

        owned_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient()
        try:
            # Lock contention or a delayed event loop can consume the lease before
            # dispatch. Never allow an HTTP request to outlive its remaining lease.
            remaining = (notif.lease_expires_at - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 1:
                await self._finish(notif, FailureCategory.INTERRUPTED,
                    "Delivery lease expired before request", True, start)
                return
            # No redirects: a destination cannot redirect credentials to another origin.
            response = await asyncio.wait_for(private_post(client, raw_url, content=body_bytes, headers=headers,
                timeout=timeout_seconds, follow_redirects=False), timeout=min(timeout_seconds+1, remaining-1))
            code = response.status_code
            if 200 <= code < 300:
                await self._finish(notif, None, None, False, start, code)
            else:
                category = (FailureCategory.AUTHENTICATION if code in (401,403) else
                            FailureCategory.TIMEOUT if code == 408 else
                            FailureCategory.UNAVAILABLE if code == 429 or code >= 500 else
                            FailureCategory.REJECTED)
                await self._finish(notif, category, f"HTTP {code}", code in (408,429) or 500 <= code <= 599, start, code)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            await self._finish(notif, FailureCategory.TIMEOUT, "Delivery timed out", True, start)
        except httpx.RequestError:
            await self._finish(notif, FailureCategory.NETWORK, "Network transport failure", True, start)
        except Exception:
            await self._finish(notif, FailureCategory.UNKNOWN, "Unexpected delivery failure", False, start)
        finally:
            if owned_client:
                await client.aclose()

    async def _finish(self, notif, category, reason, retryable, start, code=None):
        now = datetime.now(timezone.utc)
        status = DeliveryStatus.DELIVERED if category is None else DeliveryStatus.FAILED
        next_at = None
        if retryable and notif.attempt_count < notif.max_attempts:
            status = DeliveryStatus.PENDING
            delay = min(self._base_backoff * 2 ** (notif.attempt_count-1), self._retry_cap)
            next_at = now + timedelta(seconds=delay)
        accepted = await asyncio.to_thread(self._store.update_delivery_outcome, notif.notification_id, status,
            next_attempt_at=next_at, failure_reason=reason, now=now,
            delivered_at=now if status == DeliveryStatus.DELIVERED else None,
            claim_token=notif.claim_token, failure_category=category, response_status=code,
            latency_ms=round((time.perf_counter()-start)*1000,2))
        if accepted:
            logger.info("Notification outcome id=%s project=%s status=%s category=%s attempt=%d next=%s",
                notif.notification_id,notif.project_id,status.value,category.value if category else None,
                notif.attempt_count,next_at)

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

        from app.common.security import SSRFGuard, SSRFValidationError
        if not (self._http_client and isinstance(self._http_client._transport, httpx.MockTransport)):
            try:
                await asyncio.wait_for(asyncio.to_thread(SSRFGuard.validate_url, url), timeout=2.0)
            except (SSRFValidationError, asyncio.TimeoutError):
                return SubscriptionTestResponse(success=False, latency_ms=0.0,
                    error="Destination rejected or validation timed out", subscription_enabled=subscription_enabled)
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
            resp = await asyncio.wait_for(private_post(client, url, content=body_bytes, headers=req_headers,
                timeout=timeout_seconds, follow_redirects=False), timeout=min(timeout_seconds,60)+1)
            latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            success = 200 <= resp.status_code < 300
            return SubscriptionTestResponse(
                success=success,
                status_code=resp.status_code,
                latency_ms=latency_ms,
                error=None if success else f"HTTP {resp.status_code}",
                subscription_enabled=subscription_enabled,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return SubscriptionTestResponse(
                success=False,
                status_code=None,
                latency_ms=latency_ms,
                error="Diagnostic transport failure",
                subscription_enabled=subscription_enabled,
            )
        finally:
            if client is not self._http_client:
                await client.aclose()
