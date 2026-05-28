from __future__ import annotations


class CalangoException(Exception):  # noqa: N818
    def __init__(self, message: str, *, status_code: int, error_code: str) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class NotFoundError(CalangoException):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404, error_code="not_found")


class ValidationError(CalangoException):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=422, error_code="validation_error")


class AuthenticationError(CalangoException):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=401, error_code="authentication_error")


class AuthorizationError(CalangoException):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=403, error_code="authorization_error")


class ConflictError(CalangoException):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409, error_code="conflict")


class RateLimitError(CalangoException):
    def __init__(self, message: str, *, retry_after: int = 60) -> None:
        super().__init__(message, status_code=429, error_code="rate_limit_exceeded")
        self.retry_after = retry_after


class ServiceUnavailableError(CalangoException):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=503, error_code="service_unavailable")


class ConfigurationError(CalangoException):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=500, error_code="configuration_error")
