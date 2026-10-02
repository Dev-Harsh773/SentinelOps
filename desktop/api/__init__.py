"""Desktop API client and model definitions."""

from desktop.api.client import SentinelOpsClient
from desktop.api.exceptions import (
    BackendUnavailableError,
    ConflictError,
    NotFoundError,
    SentinelOpsApiError,
    ValidationError,
)

__all__ = [
    "SentinelOpsClient",
    "SentinelOpsApiError",
    "BackendUnavailableError",
    "NotFoundError",
    "ConflictError",
    "ValidationError",
]
