"""Typed exceptions for desktop API client operations."""


class SentinelOpsApiError(Exception):
    """Base exception for desktop API communication errors."""

    def __init__(self, message: str, status_code: int = 0, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail


class BackendUnavailableError(SentinelOpsApiError):
    """Raised when backend connection fails or times out."""

    pass


class NotFoundError(SentinelOpsApiError):
    """Raised when a requested resource returns HTTP 404."""

    pass


class ConflictError(SentinelOpsApiError):
    """Raised when an operation conflicts with current state (HTTP 409)."""

    pass


class ValidationError(SentinelOpsApiError):
    """Raised when input validation fails (HTTP 400 or 422)."""

    pass


class ServerError(SentinelOpsApiError):
    """Raised when backend encounters an unhandled internal error (HTTP 5xx)."""

    pass
