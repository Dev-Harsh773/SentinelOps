"""Security-focused ASGI middleware for SentinelOps."""

from __future__ import annotations

import logging
from typing import Callable
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.common.config import config

logger = logging.getLogger("sentinelops.middleware")


class SecurityHeadersMiddleware:
    """Injects essential security headers and manages conditional HSTS."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers_wrapper = Headers(scope=scope)

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))
                existing_keys = {k.decode("latin1").lower() for k, _ in raw_headers}

                def add_header(key: str, val: str) -> None:
                    if key.lower() not in existing_keys:
                        raw_headers.append((key.encode("latin1"), val.encode("latin1")))

                # Essential security headers
                add_header("X-Content-Type-Options", "nosniff")
                add_header("X-Frame-Options", "DENY")
                add_header("Referrer-Policy", "strict-origin-when-cross-origin")
                add_header("Content-Security-Policy", "default-src 'self'")

                # Conditional HSTS: only emit on HTTPS or trusted forwarded HTTPS
                is_https = scope.get("scheme") == "https"
                if not is_https and config.force_https:
                    client_ip = scope.get("client", [""])[0] if scope.get("client") else ""
                    trusted_proxies = {p.strip() for p in config.trusted_proxies.split(",") if p.strip()}
                    forwarded_proto = headers_wrapper.get("x-forwarded-proto", "").lower()
                    if client_ip in trusted_proxies and forwarded_proto == "https":
                        is_https = True

                if is_https:
                    add_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

                message["headers"] = raw_headers

            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class ContentLengthAndStreamLimitMiddleware:
    """Enforces request body size limits on buffered and streamed/chunked HTTP transfers."""

    def __init__(self, app: ASGIApp, max_body_size: int | None = None) -> None:
        self.app = app
        self.max_body_size = max_body_size if max_body_size is not None else config.max_request_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length_str = headers.get("content-length")

        # 1. Fast pre-check: Content-Length header
        if content_length_str:
            try:
                content_length = int(content_length_str)
                if content_length > self.max_body_size:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body too large ({content_length} bytes > {self.max_body_size} bytes cap)."},
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        # 2. Streaming & chunked transfer limit tracking
        received_bytes = 0

        async def tracked_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                body_chunk = message.get("body", b"")
                received_bytes += len(body_chunk)
                if received_bytes > self.max_body_size:
                    # Body exceeded limit during stream
                    raise BodySizeLimitExceededError(
                        f"Streamed body exceeded maximum allowed size of {self.max_body_size} bytes."
                    )
            return message

        try:
            await self.app(scope, tracked_receive, send)
        except BodySizeLimitExceededError as exc:
            logger.warning("Streaming body size limit exceeded: %s", exc)
            response = JSONResponse(
                status_code=413,
                content={"detail": str(exc)},
            )
            await response(scope, receive, send)


class BodySizeLimitExceededError(Exception):
    """Raised when request payload stream exceeds max body size."""
