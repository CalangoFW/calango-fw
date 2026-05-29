from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends
from fastapi_users import FastAPIUsers
from sqlalchemy.ext.asyncio import AsyncSession

from calango_identity.manager import make_get_user_manager
from calango_identity.models import User
from calango_identity.schemas import UserCreate, UserRead, UserUpdate
from calango_identity.security import make_auth_backend
from calango_identity.settings import IdentitySettings


def make_auth_router(
    settings: IdentitySettings,
    get_db: Callable,
) -> APIRouter:
    """Build and return the auth APIRouter wired to the given session dependency.

    Args:
        settings: IdentitySettings with RSA keys and expiry config.
        get_db: async generator dependency that yields an AsyncSession.
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
    router.include_router(
        fu.get_auth_router(auth_backend),
        prefix="/auth/jwt",
        tags=["auth"],
    )
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
