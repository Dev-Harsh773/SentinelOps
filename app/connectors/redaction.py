"""Secret and sensitive data redaction engine for connectors and telemetry payloads."""

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional

from app.connectors.models import ConnectorConfig

SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(password|secret|api[_-]?key|token|auth[_-]?token|bearer|private[_-]?key|access[_-]?token|client_secret|authorization)"
)

GH_TOKEN_PATTERN = re.compile(r"ghp_[A-Za-z0-9_]{20,}")
GL_TOKEN_PATTERN = re.compile(r"glpat-[A-Za-z0-9_\-]{20,}")
PEM_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----")
BEARER_PATTERN = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]{8,}")


def mask_secret(secret: Optional[str]) -> Optional[str]:
    """Mask a secret string for safe display in logs and API responses."""
    if secret is None:
        return None
    s = secret.strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "[REDACTED]"
    return f"{s[:3]}****{s[-4:]}"


def is_secret_masked(secret: Optional[str]) -> bool:
    """Check if a secret string is already in masked/redacted form."""
    if not secret:
        return False
    return "****" in secret or "[REDACTED]" in secret


def scrub_string(text: str) -> str:
    """Scrub recognized credential tokens embedded inside arbitrary string text."""
    result = GH_TOKEN_PATTERN.sub("[REDACTED_GH_TOKEN]", text)
    result = GL_TOKEN_PATTERN.sub("[REDACTED_GL_TOKEN]", result)
    result = PEM_KEY_PATTERN.sub("[REDACTED_PRIVATE_KEY]", result)
    result = BEARER_PATTERN.sub("Bearer [REDACTED]", result)
    return result


def redact_secrets(data: Any) -> Any:
    """Recursively scrub secrets from dictionaries, lists, and strings."""
    if isinstance(data, dict):
        redacted = {}
        for k, v in data.items():
            if isinstance(k, str) and SENSITIVE_KEY_PATTERN.search(k):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = redact_secrets(v)
        return redacted
    elif isinstance(data, list):
        return [redact_secrets(item) for item in data]
    elif isinstance(data, str):
        return scrub_string(data)
    else:
        return data


def mask_config_secrets(config: ConnectorConfig) -> ConnectorConfig:
    """Produce a safe copy of ConnectorConfig with auth secrets and sensitive headers masked."""
    masked_dict = config.model_dump()
    if masked_dict.get("auth_secret"):
        masked_dict["auth_secret"] = mask_secret(masked_dict["auth_secret"])
    if "headers" in masked_dict and isinstance(masked_dict["headers"], dict):
        new_headers = {}
        for hk, hv in masked_dict["headers"].items():
            if SENSITIVE_KEY_PATTERN.search(hk):
                new_headers[hk] = mask_secret(hv) if hv else hv
            else:
                new_headers[hk] = hv
        masked_dict["headers"] = new_headers
    return ConnectorConfig.model_validate(masked_dict)
