from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol, cast
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError


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


# Returns "reserved" for a new key and "collision" for an existing key.
_RESERVE_TOKEN_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) ~= 0 then
    return 'collision'
end
redis.call('HSET', KEYS[1], 'reservation', '1')
redis.call('EXPIREAT', KEYS[1], ARGV[1])
return 'reserved'
"""  # noqa: S105 - Lua source, not a credential


# Returns "stored" after linking the reserved token key to its family.
_ADD_TO_FAMILY_SCRIPT = """
redis.call('HDEL', KEYS[2], 'reservation')
redis.call('SADD', KEYS[1], ARGV[1])
redis.call('EXPIREAT', KEYS[1], ARGV[2])
return 'stored'
"""


# Returns one of: rotated (+ token metadata), missing, revoked, used, expired,
# malformed, or collision. Only the rotated branch consumes the active token.
_ROTATE_SCRIPT = """
local function valid_uuid(value)
    if not value or string.len(value) ~= 36 then
        return false
    end
    if string.sub(value, 9, 9) ~= '-'
        or string.sub(value, 14, 14) ~= '-'
        or string.sub(value, 19, 19) ~= '-'
        or string.sub(value, 24, 24) ~= '-' then
        return false
    end
    local compact = string.gsub(value, '-', '')
    return string.len(compact) == 32 and string.match(compact, '^%x+$') ~= nil
end

local status = redis.call('HGET', KEYS[1], 'status')
if not status then
    return {'missing'}
end

local user_id = redis.call('HGET', KEYS[1], 'user_id')
local family_id = redis.call('HGET', KEYS[1], 'family_id')
local expires_value = redis.call('HGET', KEYS[1], 'expires_at')
local expires_at = tonumber(expires_value)
if not valid_uuid(user_id)
    or not valid_uuid(family_id)
    or not expires_value
    or not string.match(expires_value, '^%d+$')
    or not expires_at then
    return {'malformed'}
end
if expires_at <= tonumber(ARGV[2]) then
    return {'expired'}
end

local family_key = ARGV[1] .. ':family:' .. family_id
if redis.call('EXISTS', family_key) == 0 then
    return {'malformed'}
end

if status == 'used' then
    local members = redis.call('SMEMBERS', family_key)
    for _, member in ipairs(members) do
        redis.call('HSET', member, 'status', 'revoked')
    end
    return {'used'}
end
if status == 'revoked' then
    return {'revoked'}
end
if status ~= 'active' then
    return {'malformed'}
end
if redis.call('EXISTS', KEYS[2]) ~= 0 then
    return {'collision'}
end

redis.call('HSET', KEYS[1], 'status', 'used')
redis.call(
    'HSET',
    KEYS[2],
    'user_id', user_id,
    'family_id', family_id,
    'expires_at', tostring(expires_at),
    'status', 'active'
)
redis.call('SADD', family_key, KEYS[2])
redis.call('EXPIREAT', KEYS[2], expires_at)
redis.call('EXPIREAT', family_key, expires_at)
return {'rotated', user_id, family_id, tostring(expires_at)}
"""


# Returns revoked on success (including an already revoked family), otherwise
# missing, expired, or malformed.
_REVOKE_FAMILY_SCRIPT = """
local function valid_uuid(value)
    if not value or string.len(value) ~= 36 then
        return false
    end
    if string.sub(value, 9, 9) ~= '-'
        or string.sub(value, 14, 14) ~= '-'
        or string.sub(value, 19, 19) ~= '-'
        or string.sub(value, 24, 24) ~= '-' then
        return false
    end
    local compact = string.gsub(value, '-', '')
    return string.len(compact) == 32 and string.match(compact, '^%x+$') ~= nil
end

local status = redis.call('HGET', KEYS[1], 'status')
if not status then
    return 'missing'
end

local family_id = redis.call('HGET', KEYS[1], 'family_id')
local expires_value = redis.call('HGET', KEYS[1], 'expires_at')
local expires_at = tonumber(expires_value)
if not valid_uuid(family_id)
    or not expires_value
    or not string.match(expires_value, '^%d+$')
    or not expires_at then
    return 'malformed'
end
if status ~= 'active' and status ~= 'used' and status ~= 'revoked' then
    return 'malformed'
end
if expires_at <= tonumber(ARGV[2]) then
    return 'expired'
end

local family_key = ARGV[1] .. ':family:' .. family_id
if redis.call('EXISTS', family_key) == 0 then
    return 'malformed'
end
local members = redis.call('SMEMBERS', family_key)
for _, member in ipairs(members) do
    redis.call('HSET', member, 'status', 'revoked')
end
return 'revoked'
"""


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


class RedisRefreshTokenStore:
    """A Redis-backed refresh-token store with atomic family rotation."""

    def __init__(
        self,
        redis: Redis,
        *,
        lifetime: timedelta = timedelta(days=7),
        key_prefix: str = "calango:identity:refresh",
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.redis = redis
        self._lifetime = lifetime
        self.key_prefix = key_prefix
        self._now = now or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: token_urlsafe(48))

    async def issue(self, user_id: UUID) -> RefreshTokenPair:
        family_id = uuid4()
        expires_timestamp = int((self._now() + self._lifetime).timestamp())
        expires_at = datetime.fromtimestamp(expires_timestamp, tz=UTC)

        try:
            for _ in range(_TOKEN_GENERATION_ATTEMPTS):
                token = self._token_factory()
                digest = self._digest(token)
                token_key = self._token_key(digest)
                if await self.redis.hgetall(token_key):
                    continue

                family_key = self._family_key(family_id)
                reservation = await self.redis.eval(
                    _RESERVE_TOKEN_SCRIPT,
                    1,
                    token_key,
                    expires_timestamp,
                )
                if self._text(cast(str | bytes, reservation)) == "collision":
                    continue
                await self.redis.hset(
                    token_key,
                    mapping={
                        "user_id": str(user_id),
                        "family_id": str(family_id),
                        "expires_at": expires_timestamp,
                        "status": TokenStatus.ACTIVE,
                    },
                )
                await self.redis.expireat(token_key, expires_timestamp)
                await self.redis.eval(
                    _ADD_TO_FAMILY_SCRIPT,
                    2,
                    family_key,
                    token_key,
                    token_key,
                    expires_timestamp,
                )
                return RefreshTokenPair(
                    token=token,
                    user_id=user_id,
                    family_id=family_id,
                    expires_at=expires_at,
                )
        except (RedisError, ConnectionError, TimeoutError) as exc:
            raise RefreshTokenStorageError("refresh-token store unavailable") from exc

        raise RefreshTokenStorageError("could not generate a unique refresh token")

    async def rotate(self, token: str) -> RefreshTokenPair:
        digest = self._digest(token)

        try:
            for _ in range(_TOKEN_GENERATION_ATTEMPTS):
                replacement = self._token_factory()
                replacement_digest = self._digest(replacement)
                result = await self.redis.eval(
                    _ROTATE_SCRIPT,
                    2,
                    self._token_key(digest),
                    self._token_key(replacement_digest),
                    self.key_prefix,
                    int(self._now().timestamp()),
                )
                parts = cast(list[str | bytes], result)
                code = self._text(parts[0])
                if code == "collision":
                    continue
                if code == "used":
                    raise RefreshTokenReuse
                if code != "rotated":
                    raise InvalidRefreshToken

                try:
                    user_id = UUID(self._text(parts[1]))
                    family_id = UUID(self._text(parts[2]))
                    expires_at = datetime.fromtimestamp(int(self._text(parts[3])), tz=UTC)
                except (IndexError, TypeError, ValueError):
                    raise InvalidRefreshToken from None
                return RefreshTokenPair(
                    token=replacement,
                    user_id=user_id,
                    family_id=family_id,
                    expires_at=expires_at,
                )
        except (RedisError, ConnectionError, TimeoutError) as exc:
            raise RefreshTokenStorageError("refresh-token store unavailable") from exc

        raise RefreshTokenStorageError("could not generate a unique refresh token")

    async def revoke(self, token: str) -> None:
        digest = self._digest(token)

        try:
            result = await self.redis.eval(
                _REVOKE_FAMILY_SCRIPT,
                1,
                self._token_key(digest),
                self.key_prefix,
                int(self._now().timestamp()),
            )
            if self._text(cast(str | bytes, result)) != "revoked":
                raise InvalidRefreshToken
        except (RedisError, ConnectionError, TimeoutError) as exc:
            raise RefreshTokenStorageError("refresh-token store unavailable") from exc

    @staticmethod
    def _digest(token: str) -> str:
        if len(token) < 43:
            raise InvalidRefreshToken
        return sha256(token.encode()).hexdigest()

    def _token_key(self, digest: str) -> str:
        return f"{self.key_prefix}:token:{digest}"

    def _family_key(self, family_id: UUID) -> str:
        return f"{self.key_prefix}:family:{family_id}"

    @staticmethod
    def _text(value: str | bytes) -> str:
        return value.decode() if isinstance(value, bytes) else value
