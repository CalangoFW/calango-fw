from __future__ import annotations

from datetime import timedelta
from typing import ClassVar

import redis.asyncio as redis
from fastapi import FastAPI, Request, Response
from pydantic_settings import BaseSettings
from slowapi.errors import RateLimitExceeded

from calango_identity.dependencies import enforce_authentication
from calango_identity.rate_limit import make_limiter
from calango_identity.refresh_tokens import RedisRefreshTokenStore, RefreshTokenStore
from calango_identity.router import make_auth_router, make_fastapi_users
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

    def __init__(
        self,
        settings: IdentitySettings | None = None,
        refresh_store: RefreshTokenStore | None = None,
    ) -> None:
        # pydantic-settings populates PRIVATE_KEY/PUBLIC_KEY from env at runtime;
        # ty has no pydantic plugin so it sees them as missing required args.
        self._settings = settings or IdentitySettings()  # ty: ignore[missing-argument]
        self._limiter = make_limiter(self._settings.REDIS_URL)
        self._owned_redis_client: redis.Redis | None = None
        if refresh_store is not None:
            self.refresh_store = refresh_store
        else:
            client = redis.from_url(self._settings.REDIS_URL, decode_responses=True)
            self._owned_redis_client = client
            self.refresh_store = RedisRefreshTokenStore(
                client,
                lifetime=timedelta(days=self._settings.REFRESH_TOKEN_EXPIRE_DAYS),
                key_prefix=self._settings.REFRESH_TOKEN_KEY_PREFIX,
            )

    def register(self, app: FastAPI) -> None:
        """Register auth routers, rate limiter, and exception handler."""
        existing_routes = tuple(app.routes)

        # Rate limiting middleware
        app.state.limiter = self._limiter
        # slowapi's handler signature is broader than Starlette's expected type;
        # the mismatch is benign at runtime.
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # ty: ignore[invalid-argument-type]
        if self._owned_redis_client is not None:
            app.router.add_event_handler("shutdown", self._close_owned_redis_client)

        # Auth router — uses calango-core get_db if available, else a no-op stub
        try:
            from calango.core.database import get_db
        except ImportError:

            async def get_db():  # type: ignore[misc]  # pragma: no cover
                yield None

        fastapi_users = make_fastapi_users(self._settings, get_db)
        auth_router = make_auth_router(
            settings=self._settings,
            get_db=get_db,
            refresh_store=self.refresh_store,
            limiter=self._limiter,
            fastapi_users=fastapi_users,
        )
        app.include_router(auth_router)
        enforce_authentication(
            app,
            fastapi_users.current_user(optional=True, active=True),
            existing_routes,
        )

    async def _close_owned_redis_client(self) -> None:
        """Close only the async Redis client constructed by this plugin."""
        if self._owned_redis_client is not None:
            await self._owned_redis_client.aclose()

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
- `current_user: User = Depends(get_current_user)` — inject the authenticated user
- `@public` — mark route as publicly accessible (no token required)
- `user: User = require_permission("resource:action")` — RBAC check

Auth endpoints (registered automatically):
  POST /auth/login              — returns access and refresh tokens
  POST /auth/refresh            — rotates a refresh token
  POST /auth/logout             — revokes a refresh-token family
  POST /auth/register           — create account
  POST /auth/forgot-password    — initiate password reset
  POST /auth/reset-password     — apply reset token
  GET  /users/me                — current user info

Do NOT:
- Implement authentication manually — use plugin dependencies
- Hardcode IDENTITY__PRIVATE_KEY — always use env vars or .env file
<!-- END BLOCK: identity -->"""


__all__ = ["IdentityPlugin"]
