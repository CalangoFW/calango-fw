from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import FastAPIUsers, exceptions
from sqlalchemy.ext.asyncio import AsyncSession

from calango.exceptions import AuthenticationError, ServiceUnavailableError
from calango_identity.manager import UserManager, make_get_user_manager
from calango_identity.models import User
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


def _translate_refresh_error(
    exc: Exception,
) -> AuthenticationError | ServiceUnavailableError:
    if isinstance(exc, RefreshTokenStorageError):
        return ServiceUnavailableError("Authentication service unavailable")
    return AuthenticationError("Invalid refresh token")


def make_auth_router(
    settings: IdentitySettings,
    get_db: Callable,
    refresh_store: RefreshTokenStore,
) -> APIRouter:
    """Build and return the auth APIRouter wired to the given session dependency.

    Args:
        settings: IdentitySettings with RSA keys and expiry config.
        get_db: async generator dependency that yields an AsyncSession.
        refresh_store: persistence for issuing and rotating refresh tokens.
    """
    auth_backend = make_auth_backend(settings)
    get_user_manager_factory = make_get_user_manager(settings)

    async def _get_user_manager(session: AsyncSession = Depends(get_db)):  # noqa: B008
        async for manager in get_user_manager_factory(session):
            yield manager

    fu = FastAPIUsers[User, uuid.UUID](
        _get_user_manager,
        [auth_backend],
    )

    router = APIRouter()

    @router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
    async def login(
        credentials: OAuth2PasswordRequestForm = Depends(),  # noqa: B008
        user_manager: UserManager = Depends(_get_user_manager),  # noqa: B008
    ) -> TokenResponse:
        user = await user_manager.authenticate(credentials)
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid credentials")

        try:
            refresh_token = await refresh_store.issue(user.id)
        except RefreshTokenStorageError as exc:
            raise _translate_refresh_error(exc) from exc

        return TokenResponse(
            access_token=await create_access_token(user, settings),
            refresh_token=refresh_token.token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @router.post("/auth/refresh", response_model=TokenResponse, tags=["auth"])
    async def refresh(
        body: RefreshTokenInput,
        user_manager: UserManager = Depends(_get_user_manager),  # noqa: B008
    ) -> TokenResponse:
        try:
            refresh_token = await refresh_store.rotate(body.refresh_token)
        except (InvalidRefreshToken, RefreshTokenStorageError) as exc:
            raise _translate_refresh_error(exc) from exc

        try:
            user = await user_manager.get(refresh_token.user_id)
        except exceptions.UserNotExists as exc:
            raise AuthenticationError("Invalid refresh token") from exc
        if not user.is_active:
            raise AuthenticationError("Invalid refresh token")

        return TokenResponse(
            access_token=await create_access_token(user, settings),
            refresh_token=refresh_token.token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
    async def logout(body: RefreshTokenInput) -> None:
        try:
            await refresh_store.revoke(body.refresh_token)
        except InvalidRefreshToken:
            return
        except RefreshTokenStorageError as exc:
            raise _translate_refresh_error(exc) from exc

    router.include_router(
        fu.get_register_router(UserRead, UserCreate),
        prefix="/auth",
        tags=["auth"],
    )
    router.include_router(
        fu.get_reset_password_router(),
        prefix="/auth",
        tags=["auth"],
    )
    router.include_router(
        fu.get_users_router(UserRead, UserUpdate),
        prefix="/users",
        tags=["users"],
    )

    return router
