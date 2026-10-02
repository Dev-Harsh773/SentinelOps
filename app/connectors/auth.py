"""Webhook authentication and signature verification."""

import hashlib
import hmac
from typing import Dict, Optional

from app.connectors.models import Connector


class WebhookAuthenticationError(Exception):
    """Raised when webhook request authentication fails."""

    def __init__(self, message: str = "Webhook authentication failed") -> None:
        super().__init__(message)


def verify_webhook_auth(connector: Connector, raw_body: bytes, headers: Dict[str, str]) -> bool:
    """Verify that incoming webhook request matches configured authentication credentials.

    Raises WebhookAuthenticationError on verification failure.
    Returns True if valid or if no authentication secret is configured.
    """
    secret = connector.config.auth_secret
    if not secret:
        # No authentication configured for this connector
        return True

    # Case-insensitive header lookup
    normalized_headers = {k.lower(): v for k, v in headers.items()}

    # Check 1: HMAC signature header if configured
    sig_header_name = connector.config.signature_header
    if sig_header_name:
        header_val = normalized_headers.get(sig_header_name.lower())
        if not header_val:
            raise WebhookAuthenticationError(f"Missing required signature header '{sig_header_name}'")
        return verify_hmac_signature(
            raw_body=raw_body,
            signature=header_val,
            secret=secret,
            algorithm=connector.config.signature_algorithm or "sha256",
        )

    # Check 2: Token header if configured
    tok_header_name = connector.config.token_header
    if tok_header_name:
        token_val = normalized_headers.get(tok_header_name.lower())
        if not token_val:
            raise WebhookAuthenticationError(f"Missing required auth token header '{tok_header_name}'")
        if tok_header_name.lower() == "authorization" and token_val.lower().startswith("bearer "):
            token_val = token_val[7:].strip()
        if not hmac.compare_digest(token_val, secret):
            raise WebhookAuthenticationError("Invalid authentication token")
        return True

    # Check 3: Fallback common headers if secret exists but no explicit header was configured
    # Try HMAC signatures first
    for candidate_sig in ["x-hub-signature-256", "x-webhook-signature", "x-signature-256"]:
        if candidate_sig in normalized_headers:
            return verify_hmac_signature(
                raw_body=raw_body,
                signature=normalized_headers[candidate_sig],
                secret=secret,
                algorithm="sha256",
            )

    # Try token headers
    for candidate_tok in ["x-webhook-token", "x-api-key", "authorization"]:
        if candidate_tok in normalized_headers:
            tok_val = normalized_headers[candidate_tok]
            if candidate_tok == "authorization" and tok_val.lower().startswith("bearer "):
                tok_val = tok_val[7:].strip()
            if hmac.compare_digest(tok_val, secret):
                return True
            raise WebhookAuthenticationError("Invalid authentication token")

    raise WebhookAuthenticationError("No matching authentication signature or token header provided")


def verify_hmac_signature(raw_body: bytes, signature: str, secret: str, algorithm: str = "sha256") -> bool:
    """Verify an HMAC signature using timing-safe comparison."""
    clean_sig = signature.strip()
    # Handle prefixes like 'sha256=abcdef...'
    if "=" in clean_sig:
        prefix, clean_sig = clean_sig.split("=", 1)

    algo = getattr(hashlib, algorithm.lower(), None)
    if not algo:
        raise WebhookAuthenticationError(f"Unsupported HMAC algorithm: {algorithm}")

    computed_digest = hmac.new(secret.encode("utf-8"), raw_body, algo).hexdigest()

    if not hmac.compare_digest(clean_sig.lower(), computed_digest.lower()):
        raise WebhookAuthenticationError("HMAC signature mismatch")

    return True
