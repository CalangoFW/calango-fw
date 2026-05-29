from __future__ import annotations

from typing import ClassVar

from fastapi import FastAPI, Request, Response
from pydantic_settings import BaseSettings
from slowapi.errors import RateLimitExceeded

from calango_identity.rate_limit import make_limiter
from calango_identity.router import make_auth_router
from calango_identity.settings import IdentitySettings


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    from slowapi import _rate_limit_exceeded_handler as _handler

    return _handler(request, exc)


class IdentityPlugin:
    """Calango Identity Plugin — JWT RS256 auth, RBAC, rate-limited endpoints.

    Usage:
        from calango_identity import IdentityPlugin
        app = Calango(settings=settings)
        app.include_plugin(IdentityPlugin())
    """

    name = "identity"
    version = "0.1.0"
    requires: ClassVar[list[str]] = ["calango-core>=0.1.0", "calango-plugin-base>=0.1.0"]

    def __init__(self, settings: IdentitySettings | None = None) -> None:
        self._settings = settings or IdentitySettings()
        self._limiter = make_limiter(self._settings.REDIS_URL)

    def register(self, app: FastAPI) -> None:
        """Register auth routers, rate limiter, and exception handler."""
        # Rate limiting middleware
        app.state.limiter = self._limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

        # Auth router — uses calango-core get_db if available, else a no-op stub
        try:
            from calango.core.database import get_db
        except ImportError:

            async def get_db():  # type: ignore[misc]  # pragma: no cover
                yield None

        auth_router = make_auth_router(settings=self._settings, get_db=get_db)
        app.include_router(auth_router)

    def migrations(self) -> list[str]:
        """Return Alembic migration paths for identity tables."""
        return ["calango_identity.migrations"]

    def settings(self) -> type[BaseSettings]:
        """Return the IdentitySettings class."""
        return IdentitySettings

    def test_fixtures(self) -> list:
        """pytest fixtures for projects using calango-identity."""
        return []

    def context_md(self) -> str:
        """CLAUDE.md block describing the identity plugin."""
        return """<!-- BLOCK: identity -->
## Plugin: Identity

JWT RS256 authentication with RBAC. All routes require authentication by default.

Patterns:
- `@public` — mark route as publicly accessible (no token required)
- `user: User = require_permission("resource:action")` — RBAC check

Auth endpoints (registered automatically):
  POST /auth/jwt/login          — returns access_token
  POST /auth/register           — create account
  POST /auth/forgot-password    — initiate password reset
  POST /auth/reset-password     — apply reset token
  GET  /users/me                — current user info

Do NOT:
- Implement authentication manually — use plugin dependencies
- Hardcode IDENTITY__PRIVATE_KEY — always use env vars or .env file
<!-- END BLOCK: identity -->"""


__all__ = ["IdentityPlugin"]
