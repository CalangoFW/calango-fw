from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def make_limiter(storage_uri: str) -> Limiter:
    """Create a slowapi Limiter backed by the given storage URI.

    For production: storage_uri = "redis://localhost:6379/0"
    For tests: storage_uri = "memory://"
    """
    return Limiter(key_func=get_remote_address, storage_uri=storage_uri)


def get_email_key(request: Request) -> str:
    """Key function for per-email rate limiting on login endpoint.

    Falls back to IP address if login_email is not set on request.state.
    """
    email = getattr(request.state, "login_email", None)
    if email:
        return email
    return get_remote_address(request)
