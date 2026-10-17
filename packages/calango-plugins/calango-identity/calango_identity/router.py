from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from functools import wraps
from json import JSONDecodeError
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.routing import APIRoute
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import FastAPIUsers, exceptions
from limits.errors import StorageError
from pydantic import ValidationError
from redis.exceptions import RedisError
from slowapi import Limiter
from sqlalchemy.ext.asyncio import AsyncSession

from calango.exceptions import AuthenticationError, ServiceUnavailableError
from calango_identity.dependencies import identity_public
from calango_identity.manager import UserManager, make_get_user_manager
from calango_identity.models import User
from calango_identity.rate_limit import capture_login_email, get_email_key
from calango_identity.refresh_tokens import (
    InvalidRefreshToken,
    RefreshTokenStorageError,
    RefreshTokenStore,
)
from calango_identity.schemas import (
    RefreshTokenInput,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from calango_identity.security import create_access_token, make_auth_backend
from calango_identity.settings import IdentitySettings

logger = logging.getLogger(__name__)

_REFRESH_TOKEN_OPENAPI_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": RefreshTokenInput.model_json_schema(),
            }
        },
    }
}


def _mark_identity_public_routes(router: APIRouter) -> APIRouter:
    """Mark every direct route in an Identity-owned anonymous router."""
    for route in router.routes:
        if isinstance(route, APIRoute):
            identity_public(route.endpoint)
    return router


def _log_storage_unavailable(component: str, exc: Exception) -> None:
    """Record a storage outage by exception type only; messages may carry secrets."""
    logger.error(
        "Identity %s storage unavailable",
        component,
        extra={"error_type": type(exc).__name__},
    )


def set_no_store(response: Response) -> None:
    """Forbid shared and browser caches from storing issued credentials."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _translate_rate_limit_storage_errors(endpoint: Callable[..., Awaitable[Any]]) -> Any:
    """Report rate-limit storage outages with the uniform authentication 503."""

    @wraps(endpoint)
    async def translated(*args: Any, **kwargs: Any) -> Any:
        try:
            return await endpoint(*args, **kwargs)
        except (RedisError, StorageError) as exc:
            _log_storage_unavailable("rate limit", exc)
        raise ServiceUnavailableError("Authentication service unavailable")

    return translated


def _translate_refresh_error(
    exc: Exception,
) -> AuthenticationError | ServiceUnavailableError:
    if isinstance(exc, RefreshTokenStorageError):
        _log_storage_unavailable("refresh token", exc)
        return ServiceUnavailableError("Authentication service unavailable")
    return AuthenticationError("Invalid refresh token")


async def _parse_refresh_token(request: Request) -> str:
    try:
        payload = await request.json()
        refresh_token = RefreshTokenInput.model_validate(payload).refresh_token
    except (JSONDecodeError, UnicodeDecodeError, ValidationError):
        pass
    else:
        return refresh_token
    raise AuthenticationError("Invalid refresh token") from None


def make_fastapi_users(
    settings: IdentitySettings,
    get_db: Callable,
) -> FastAPIUsers[User, uuid.UUID]:
    """Build the shared FastAPI Users object for routers and global auth."""
    auth_backend = make_auth_backend(settings)
    get_user_manager_factory = make_get_user_manager(settings)

    async def _get_user_manager(session: AsyncSession = Depends(get_db)):  # noqa: B008
        async for manager in get_user_manager_factory(session):
            yield manager

    return FastAPIUsers[User, uuid.UUID](_get_user_manager, [auth_backend])


def make_auth_router(
    settings: IdentitySettings,
    get_db: Callable,
    refresh_store: RefreshTokenStore,
    limiter: Limiter,
    fastapi_users: FastAPIUsers[User, uuid.UUID] | None = None,
) -> APIRouter:
    """Build and return the auth APIRouter wired to the given session dependency.

    Args:
        settings: IdentitySettings with RSA keys and expiry config.
        get_db: async generator dependency that yields an AsyncSession.
        refresh_store: persistence for issuing and rotating refresh tokens.
        limiter: shared SlowAPI limiter also installed on the application.
        fastapi_users: optional shared authentication bundle from the plugin.
    """
    fu = fastapi_users or make_fastapi_users(settings, get_db)
    get_user_manager = fu.get_user_manager

    router = APIRouter()

    @router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
    @identity_public
    @_translate_rate_limit_storage_errors
    @limiter.limit(f"{settings.RATE_LIMIT_LOGIN_PER_MINUTE}/minute")
    @limiter.limit(
        f"{settings.RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL}/hour",
        key_func=get_email_key,
    )
    async def login(
        request: Request,
        response: Response,
        credentials: OAuth2PasswordRequestForm = Depends(capture_login_email),  # noqa: B008
        user_manager: UserManager = Depends(get_user_manager),  # noqa: B008
    ) -> TokenResponse:
        user = await user_manager.authenticate(credentials)
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid credentials")

        try:
            refresh_token = await refresh_store.issue(user.id)
        except RefreshTokenStorageError as exc:
            raise _translate_refresh_error(exc) from exc

        token_response = TokenResponse(
            access_token=await create_access_token(user, settings),
            refresh_token=refresh_token.token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        await user_manager.on_after_login(user, request, response)
        set_no_store(response)
        return token_response

    @router.post(
        "/auth/refresh",
        response_model=TokenResponse,
        tags=["auth"],
        openapi_extra=_REFRESH_TOKEN_OPENAPI_BODY,
    )
    @identity_public
    async def refresh(
        request: Request,
        response: Response,
        user_manager: UserManager = Depends(get_user_manager),  # noqa: B008
    ) -> TokenResponse:
        token = await _parse_refresh_token(request)
        try:
            refresh_token = await refresh_store.rotate(token)
        except (InvalidRefreshToken, RefreshTokenStorageError) as exc:
            raise _translate_refresh_error(exc) from exc

        try:
            user = await user_manager.get(refresh_token.user_id)
        except exceptions.UserNotExists as exc:
            raise AuthenticationError("Invalid refresh token") from exc
        if not user.is_active:
            raise AuthenticationError("Invalid refresh token")

        set_no_store(response)
        return TokenResponse(
            access_token=await create_access_token(user, settings),
            refresh_token=refresh_token.token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @router.post(
        "/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["auth"],
        openapi_extra=_REFRESH_TOKEN_OPENAPI_BODY,
    )
    @identity_public
    async def logout(request: Request) -> None:
        token = await _parse_refresh_token(request)
        try:
            await refresh_store.revoke(token)
        except (InvalidRefreshToken, RefreshTokenStorageError) as exc:
            raise _translate_refresh_error(exc) from exc

    router.include_router(
        _mark_identity_public_routes(fu.get_register_router(UserRead, UserCreate)),
        prefix="/auth",
        tags=["auth"],
    )
    router.include_router(
        _mark_identity_public_routes(fu.get_reset_password_router()),
        prefix="/auth",
        tags=["auth"],
    )
    router.include_router(
        fu.get_users_router(UserRead, UserUpdate),
        prefix="/users",
        tags=["users"],
    )

    return router
