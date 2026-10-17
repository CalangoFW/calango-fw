from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from importlib import import_module
from importlib.resources import files
from typing import ClassVar

import redis.asyncio as redis
from calango_plugin_base import PluginMigration
from fastapi import FastAPI, Request, Response
from pydantic_settings import BaseSettings
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from calango import Calango
from calango_identity.dependencies import (
    make_authentication_guard,
    make_optional_current_user_resolver,
)
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
        limiter: Limiter | None = None,
    ) -> None:
        self._settings = settings or IdentitySettings()
        self._owned_limiter: Limiter | None = None
        if limiter is None:
            limiter = make_limiter(
                self._settings.REDIS_URL,
                self._settings.TRUSTED_PROXIES,
            )
            self._owned_limiter = limiter
        self._limiter = limiter
        self._owned_redis_client: redis.Redis | None = None
        self._owned_resources_closed = False
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
        if not isinstance(app, Calango):
            raise TypeError("IdentityPlugin requires a Calango application")

        # Rate limiting middleware
        app.state.limiter = self._limiter
        # slowapi's handler signature is broader than Starlette's expected type;
        # the mismatch is benign at runtime.
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # ty: ignore[invalid-argument-type]

        session_dependency = app.database.session
        fastapi_users = make_fastapi_users(self._settings, session_dependency)
        optional_current_user = fastapi_users.current_user(optional=True, active=True)
        app.add_dependency_request_guard(
            make_authentication_guard(optional_current_user),
            dependency=optional_current_user,
            resolver=make_optional_current_user_resolver(
                self._settings,
                session_dependency,
            ),
        )
        auth_router = make_auth_router(
            settings=self._settings,
            get_db=session_dependency,
            refresh_store=self.refresh_store,
            limiter=self._limiter,
            fastapi_users=fastapi_users,
        )
        app.include_router(auth_router)

        @asynccontextmanager
        async def owned_resource_lifespan(_app: Calango):
            try:
                yield
            finally:
                await self._close_owned_resources()

        app.add_plugin_lifespan(owned_resource_lifespan)

    async def _close_owned_resources(self) -> None:
        """Close constructed async and sync backends at most once."""
        if self._owned_resources_closed:
            return
        self._owned_resources_closed = True

        try:
            if self._owned_redis_client is not None:
                await self._owned_redis_client.aclose()
        finally:
            if self._owned_limiter is not None:
                storage = self._owned_limiter.limiter.storage
                storage_client = getattr(storage, "storage", None)
                close = getattr(storage_client, "close", None)
                if callable(close):
                    close()

    def import_models(self) -> None:
        """Register Identity models explicitly with canonical metadata."""
        import_module("calango_identity.models")

    def migrations(self) -> tuple[PluginMigration, ...]:
        """Return the wheel-safe location for identity revisions."""
        versions = files("calango_identity.migrations.versions")
        return (PluginMigration("identity", versions, ()),)

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
