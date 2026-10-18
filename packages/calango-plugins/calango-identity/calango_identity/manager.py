from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import Request, Response
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from calango_identity.events import IdentityEvents
from calango_identity.models import User
from calango_identity.settings import IdentitySettings

logger = logging.getLogger(__name__)


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
    def __init__(
        self,
        user_db: SQLAlchemyUserDatabase,
        settings: IdentitySettings,
        events: IdentityEvents | None = None,
    ) -> None:
        super().__init__(user_db)
        self.reset_password_token_secret = derive_token_secret(settings, "password-reset")
        self.verification_token_secret = derive_token_secret(settings, "verification")
        self._events = events

    async def _notify(
        self,
        event: str,
        deliver: Callable[[IdentityEvents], Awaitable[None]],
    ) -> None:
        """Hand an event to the provider; its failure never changes the response.

        Forgot-password responses must not reveal whether an account exists, so a
        delivery error is logged by type only and the provider owns retries.
        """
        events = self._events
        if events is None:
            return
        try:
            await deliver(events)
        except Exception as exc:
            logger.error(
                "Identity %s event delivery failed",
                event,
                extra={"error_type": type(exc).__name__},
            )

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        await self._notify("registered", lambda events: events.on_registered(user, request))

    async def on_after_login(
        self,
        user: User,
        request: Request | None = None,
        response: Response | None = None,
    ) -> None:
        await self._notify("login", lambda events: events.on_login(user, request, response))

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        await self._notify(
            "password_reset",
            lambda events: events.send_password_reset(user, token, request),
        )

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        await self._notify(
            "verification",
            lambda events: events.send_verification(user, token, request),
        )


def make_get_user_manager(settings: IdentitySettings, events: IdentityEvents | None = None):
    """Returns a FastAPI dependency that yields UserManager given an AsyncSession."""

    async def get_user_manager(session: AsyncSession) -> AsyncGenerator[UserManager, None]:
        yield UserManager(SQLAlchemyUserDatabase(session, User), settings, events)

    return get_user_manager
