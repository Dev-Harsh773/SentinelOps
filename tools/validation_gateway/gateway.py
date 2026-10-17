"""Validation restricted ingress gateway.

Exposes exclusively:
    POST /connectors/{connector_id}/ingest

Forwards strictly to fixed upstream SentinelOps backend:
    http://127.0.0.1:8000

Guarantees:
- Rejects all other methods, paths, and endpoints.
- Enforces strict 1 MB request body cap.
- Preserves X-Sentinel-Secret, Content-Type, X-Request-ID.
- Strictly never logs secrets or tokens.
- Never accepts arbitrary upstream destinations.
- Isolated development/E2E validation infrastructure only (not for production).
"""

import logging
import re
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
import httpx

logger = logging.getLogger("validation_gateway")

UPSTREAM_BASE_URL = "http://127.0.0.1:8000"
MAX_BODY_BYTES = 1_048_576  # 1 MB
INGEST_PATH_PATTERN = re.compile(r"^/connectors/([a-zA-Z0-9_\-\.]+)/ingest$")


def create_gateway_app(upstream_url: str = UPSTREAM_BASE_URL) -> FastAPI:
    """Factory creating restricted validation gateway application."""
    if upstream_url != UPSTREAM_BASE_URL:
        raise ValueError("Validation gateway upstream must be http://127.0.0.1:8000")
    app = FastAPI(
        title="SentinelOps Validation Gateway",
        description="Restricted validation ingress proxy exposing only webhook ingestion.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def filter_and_proxy_request(request: Request, call_next):
        path = request.url.path
        method = request.method

        match = INGEST_PATH_PATTERN.match(path)
        if not match:
            return Response(
                status_code=status.HTTP_404_NOT_FOUND,
                content=b'{"detail":"Endpoint not found or rejected by restricted validation ingress."}',
                media_type="application/json",
            )

        if method != "POST":
            return Response(
                status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                content=b'{"detail":"Method not allowed."}',
                media_type="application/json",
            )

        # Enforce 1 MB body limit
        content_length_header = request.headers.get("content-length")
        if content_length_header:
            try:
                cl = int(content_length_header)
                if cl > MAX_BODY_BYTES:
                    return Response(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        content=b'{"detail":"Payload exceeds 1 MB limit."}',
                        media_type="application/json",
                    )
            except ValueError:
                pass

        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return Response(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content=b'{"detail":"Payload exceeds 1 MB limit."}',
                    media_type="application/json",
                )
            body.extend(chunk)

        connector_id = match.group(1)

        # Headers to forward
        forward_headers = {}
        for header_name in ["content-type", "x-sentinel-secret", "x-webhook-token", "x-request-id"]:
            val = request.headers.get(header_name)
            if val:
                forward_headers[header_name] = val

        # Forward upstream to fixed target
        target_url = f"{upstream_url}/connectors/{connector_id}/ingest"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    target_url,
                    content=bytes(body),
                    headers=forward_headers,
                )
                logger.info(
                    "Proxied ingest for connector '%s' -> upstream HTTP %d",
                    connector_id,
                    resp.status_code,
                )
                # Strip hop-by-hop headers
                excluded_headers = {"content-length", "content-encoding", "transfer-encoding", "connection"}
                resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}

                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    headers=resp_headers,
                    media_type=resp.headers.get("content-type"),
                )
        except Exception as exc:
            logger.error("Upstream proxy failure for connector '%s' (%s)", connector_id, type(exc).__name__)
            return Response(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content=b'{"detail":"Upstream SentinelOps gateway error."}',
                media_type="application/json",
            )

    return app


gateway_app = create_gateway_app()
