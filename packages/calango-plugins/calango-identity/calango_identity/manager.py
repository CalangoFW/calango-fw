from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from calango_identity.models import User
from calango_identity.settings import IdentitySettings


def derive_token_secret(settings: IdentitySettings, purpose: str) -> str:
    """Derive a purpose-bound HMAC secret from the Identity signing key.

    FastAPI Users signs reset and verification tokens with HS256, and PyJWT
    rejects PEM keys as HMAC secrets, so the RSA key is never used directly.
    """
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"calango-identity:{purpose}".encode(),
    )
    return kdf.derive(settings.PRIVATE_KEY.get_secret_value().encode()).hex()


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    def __init__(self, user_db: SQLAlchemyUserDatabase, settings: IdentitySettings) -> None:
        super().__init__(user_db)
        self.reset_password_token_secret = derive_token_secret(settings, "password-reset")
        self.verification_token_secret = derive_token_secret(settings, "verification")

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        pass  # Hook: send welcome email, etc.

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        pass  # Hook: send reset email with token


def make_get_user_manager(settings: IdentitySettings):
    """Returns a FastAPI dependency that yields UserManager given an AsyncSession."""

    async def get_user_manager(session: AsyncSession) -> AsyncGenerator[UserManager, None]:
        yield UserManager(SQLAlchemyUserDatabase(session, User), settings)

    return get_user_manager
