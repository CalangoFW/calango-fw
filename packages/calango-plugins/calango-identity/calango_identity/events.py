from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from fastapi import Request, Response

from calango_identity.models import User

logger = logging.getLogger(__name__)


@runtime_checkable
class IdentityEvents(Protocol):
    """Account lifecycle events Identity hands to the application.

    Identity decides *when* an event happens; the provider decides *how* it is
    delivered (email, SMS, queue) and owns retries. A provider failure is logged
    by error type and never changes the HTTP response.
    """

    async def on_registered(self, user: User, request: Request | None) -> None: ...

    async def on_login(
        self,
        user: User,
        request: Request | None,
        response: Response | None,
    ) -> None: ...

    async def send_password_reset(
        self,
        user: User,
        token: str,
        request: Request | None,
    ) -> None: ...

    async def send_verification(
        self,
        user: User,
        token: str,
        request: Request | None,
    ) -> None: ...


class LoggingIdentityEvents:
    """Development-only provider that records events without delivering tokens.

    It logs the event name and opaque user id only — never email addresses or
    tokens — so reset and verification links cannot be completed with it.
    """

    async def on_registered(self, user: User, request: Request | None) -> None:
        _log_event("registered", user)

    async def on_login(
        self,
        user: User,
        request: Request | None,
        response: Response | None,
    ) -> None:
        _log_event("login", user)

    async def send_password_reset(
        self,
        user: User,
        token: str,
        request: Request | None,
    ) -> None:
        _log_event("password_reset", user)

    async def send_verification(
        self,
        user: User,
        token: str,
        request: Request | None,
    ) -> None:
        _log_event("verification", user)


def _log_event(event: str, user: User) -> None:
    logger.info("Identity event %s for user %s", event, user.id)
