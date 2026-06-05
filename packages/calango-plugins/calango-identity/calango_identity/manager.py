from __future__ import annotations

import uuid

from fastapi import Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase

from calango_identity.models import User
from calango_identity.settings import IdentitySettings


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    def __init__(self, user_db: SQLAlchemyUserDatabase, settings: IdentitySettings) -> None:
        super().__init__(user_db)
        self.reset_password_token_secret = settings.PRIVATE_KEY
        self.verification_token_secret = settings.PRIVATE_KEY

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        pass  # Hook: send welcome email, etc.

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        pass  # Hook: send reset email with token


def make_get_user_manager(settings: IdentitySettings):
    """Returns a FastAPI dependency that yields UserManager given an AsyncSession."""

    async def get_user_manager(session) -> UserManager:
        yield UserManager(SQLAlchemyUserDatabase(session, User), settings)

    return get_user_manager
