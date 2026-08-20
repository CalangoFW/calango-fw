from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID, uuid4


class InvalidRefreshToken(Exception):  # noqa: N818 - public interface is specified
    """The supplied refresh token cannot authorize a session operation."""


class RefreshTokenReuse(InvalidRefreshToken):
    """A consumed refresh token was presented again."""


class RefreshTokenStorageError(Exception):
    """The refresh-token store is unavailable."""


class TokenStatus(StrEnum):
    ACTIVE = "active"
    USED = "used"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class RefreshTokenPair:
    token: str
    user_id: UUID
    family_id: UUID
    expires_at: datetime


class RefreshTokenStore(Protocol):
    async def issue(self, user_id: UUID) -> RefreshTokenPair: ...

    async def rotate(self, token: str) -> RefreshTokenPair: ...

    async def revoke(self, token: str) -> None: ...


@dataclass(slots=True)
class _RefreshTokenRecord:
    user_id: UUID
    family_id: UUID
    expires_at: datetime
    status: TokenStatus


_TOKEN_GENERATION_ATTEMPTS = 3


class InMemoryRefreshTokenStore:
    """A deterministic refresh-token store suitable for development and tests."""

    def __init__(
        self,
        *,
        lifetime: timedelta = timedelta(days=7),
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._lifetime = lifetime
        self._now = now or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: token_urlsafe(48))
        self._lock = asyncio.Lock()
        self.records: dict[str, _RefreshTokenRecord] = {}

    async def issue(self, user_id: UUID) -> RefreshTokenPair:
        family_id = uuid4()
        expires_at = self._now() + self._lifetime

        async with self._lock:
            token, digest = self._new_unique_token()
            self.records[digest] = _RefreshTokenRecord(
                user_id=user_id,
                family_id=family_id,
                expires_at=expires_at,
                status=TokenStatus.ACTIVE,
            )

        return RefreshTokenPair(
            token=token,
            user_id=user_id,
            family_id=family_id,
            expires_at=expires_at,
        )

    async def rotate(self, token: str) -> RefreshTokenPair:
        digest = self._digest(token)

        async with self._lock:
            record = self.records.get(digest)
            if record is None or record.expires_at <= self._now():
                raise InvalidRefreshToken
            if record.status is TokenStatus.USED:
                self._revoke_family(record.family_id)
                raise RefreshTokenReuse
            if record.status is TokenStatus.REVOKED:
                raise InvalidRefreshToken

            replacement, replacement_digest = self._new_unique_token()
            record.status = TokenStatus.USED
            self.records[replacement_digest] = _RefreshTokenRecord(
                user_id=record.user_id,
                family_id=record.family_id,
                expires_at=record.expires_at,
                status=TokenStatus.ACTIVE,
            )

        return RefreshTokenPair(
            token=replacement,
            user_id=record.user_id,
            family_id=record.family_id,
            expires_at=record.expires_at,
        )

    async def revoke(self, token: str) -> None:
        digest = self._digest(token)

        async with self._lock:
            record = self.records.get(digest)
            if record is None:
                raise InvalidRefreshToken
            self._revoke_family(record.family_id)

    @staticmethod
    def _digest(token: str) -> str:
        if len(token) < 43:
            raise InvalidRefreshToken
        return sha256(token.encode()).hexdigest()

    def _new_unique_token(self) -> tuple[str, str]:
        for _ in range(_TOKEN_GENERATION_ATTEMPTS):
            token = self._token_factory()
            digest = self._digest(token)
            if digest not in self.records:
                return token, digest
        raise RefreshTokenStorageError("could not generate a unique refresh token")

    def _revoke_family(self, family_id: UUID) -> None:
        for record in self.records.values():
            if record.family_id == family_id:
                record.status = TokenStatus.REVOKED
