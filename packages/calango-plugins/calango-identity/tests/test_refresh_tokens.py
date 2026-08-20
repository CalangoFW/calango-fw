from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from calango_identity.refresh_tokens import (
    InMemoryRefreshTokenStore,
    InvalidRefreshToken,
    RedisRefreshTokenStore,
    RefreshTokenReuse,
    RefreshTokenStorageError,
)
from fakeredis.aioredis import FakeRedis

NOW = datetime(2026, 8, 20, tzinfo=UTC)
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def store() -> InMemoryRefreshTokenStore:
    secrets = iter(("a" * 64, "b" * 64, "c" * 64))
    return InMemoryRefreshTokenStore(
        lifetime=timedelta(days=7),
        now=lambda: NOW,
        token_factory=lambda: next(secrets),
    )


@pytest.fixture
def redis_store() -> RedisRefreshTokenStore:
    redis = FakeRedis(decode_responses=True)
    secrets = iter(f"{letter}" * 64 for letter in "defghijklm")
    return RedisRefreshTokenStore(
        redis,
        lifetime=timedelta(days=7),
        key_prefix="test:refresh",
        now=lambda: NOW,
        token_factory=lambda: next(secrets),
    )


async def test_issue_returns_secret_but_stores_only_its_digest(store):
    issued = await store.issue(USER_ID)
    assert issued.token == "a" * 64
    assert issued.expires_at == NOW + timedelta(days=7)
    assert issued.token not in repr(store.records)


async def test_rotate_invalidates_old_token_without_extending_family(store):
    issued = await store.issue(USER_ID)
    rotated = await store.rotate(issued.token)
    assert rotated.token == "b" * 64
    assert rotated.family_id == issued.family_id
    assert rotated.expires_at == issued.expires_at


async def test_reuse_revokes_the_whole_family(store):
    issued = await store.issue(USER_ID)
    rotated = await store.rotate(issued.token)
    with pytest.raises(RefreshTokenReuse):
        await store.rotate(issued.token)
    with pytest.raises(InvalidRefreshToken):
        await store.rotate(rotated.token)


async def test_only_one_concurrent_rotation_succeeds(store):
    issued = await store.issue(USER_ID)
    results = await asyncio.gather(
        store.rotate(issued.token),
        store.rotate(issued.token),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1


async def test_revoke_family_is_idempotent(store):
    issued = await store.issue(USER_ID)
    await store.revoke(issued.token)
    await store.revoke(issued.token)


async def test_in_memory_revoke_rejects_expired_token():
    current_time = [NOW]
    store = InMemoryRefreshTokenStore(
        lifetime=timedelta(days=7),
        now=lambda: current_time[0],
        token_factory=lambda: "a" * 64,
    )
    issued = await store.issue(USER_ID)
    current_time[0] = NOW + timedelta(days=8)

    with pytest.raises(InvalidRefreshToken):
        await store.revoke(issued.token)


async def test_rotate_retries_a_colliding_replacement_without_overwriting_original():
    secrets = iter(("a" * 64, "a" * 64, "b" * 64))
    store = InMemoryRefreshTokenStore(
        lifetime=timedelta(days=7),
        now=lambda: NOW,
        token_factory=lambda: next(secrets),
    )
    issued = await store.issue(USER_ID)

    rotated = await store.rotate(issued.token)

    assert rotated.token == "b" * 64
    with pytest.raises(RefreshTokenReuse):
        await store.rotate(issued.token)


async def test_issue_raises_storage_error_when_factory_cannot_produce_unique_token():
    store = InMemoryRefreshTokenStore(
        lifetime=timedelta(days=7),
        now=lambda: NOW,
        token_factory=lambda: "a" * 64,
    )
    await store.issue(USER_ID)

    with pytest.raises(RefreshTokenStorageError, match="unique"):
        await store.issue(USER_ID)


async def test_rotate_leaves_token_active_when_factory_cannot_produce_unique_token():
    token = ["a" * 64]
    store = InMemoryRefreshTokenStore(
        lifetime=timedelta(days=7),
        now=lambda: NOW,
        token_factory=lambda: token[0],
    )
    issued = await store.issue(USER_ID)

    with pytest.raises(RefreshTokenStorageError, match="unique"):
        await store.rotate(issued.token)

    token[0] = "b" * 64
    rotated = await store.rotate(issued.token)
    assert rotated.token == "b" * 64


async def test_redis_store_never_uses_raw_token_as_key(redis_store):
    issued = await redis_store.issue(USER_ID)
    keys = await redis_store.redis.keys("*")
    assert all(issued.token not in key for key in keys)


async def test_redis_store_never_persists_raw_token_material(redis_store):
    issued = await redis_store.issue(USER_ID)
    persisted = []
    for key in await redis_store.redis.keys("*"):
        persisted.append(key)
        key_type = await redis_store.redis.type(key)
        if key_type == "hash":
            persisted.append(await redis_store.redis.hgetall(key))
        elif key_type == "set":
            persisted.append(await redis_store.redis.smembers(key))
    assert issued.token not in repr(persisted)


async def test_redis_rotation_preserves_absolute_expiry(redis_store):
    issued = await redis_store.issue(USER_ID)
    rotated = await redis_store.rotate(issued.token)
    assert rotated.expires_at == issued.expires_at

    expected_expiry = int(issued.expires_at.timestamp())
    token_keys = [
        f"test:refresh:token:{sha256(value.token.encode()).hexdigest()}"
        for value in (issued, rotated)
    ]
    family_key = f"test:refresh:family:{issued.family_id}"
    assert [await redis_store.redis.expiretime(key) for key in token_keys] == [
        expected_expiry,
        expected_expiry,
    ]
    assert await redis_store.redis.expiretime(family_key) == expected_expiry


async def test_redis_issue_reports_its_integer_storage_expiry():
    precise_now = NOW.replace(microsecond=123456)
    store = RedisRefreshTokenStore(
        FakeRedis(decode_responses=True),
        lifetime=timedelta(days=7),
        key_prefix="test:refresh",
        now=lambda: precise_now,
        token_factory=lambda: "d" * 64,
    )

    issued = await store.issue(USER_ID)

    expected_timestamp = int((precise_now + timedelta(days=7)).timestamp())
    assert issued.expires_at == datetime.fromtimestamp(expected_timestamp, tz=UTC)


async def test_redis_reuse_revokes_the_whole_family(redis_store):
    issued = await redis_store.issue(USER_ID)
    rotated = await redis_store.rotate(issued.token)

    with pytest.raises(RefreshTokenReuse):
        await redis_store.rotate(issued.token)
    with pytest.raises(InvalidRefreshToken):
        await redis_store.rotate(rotated.token)


async def test_redis_allows_only_one_concurrent_rotation(redis_store):
    issued = await redis_store.issue(USER_ID)
    results = await asyncio.gather(
        redis_store.rotate(issued.token),
        redis_store.rotate(issued.token),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1


async def test_redis_family_revocation_is_idempotent(redis_store):
    issued = await redis_store.issue(USER_ID)
    await redis_store.revoke(issued.token)
    await redis_store.revoke(issued.token)
    with pytest.raises(InvalidRefreshToken):
        await redis_store.rotate(issued.token)


async def test_redis_rotation_retries_digest_collisions():
    secrets = iter(("d" * 64, "d" * 64, "e" * 64))
    store = RedisRefreshTokenStore(
        FakeRedis(decode_responses=True),
        lifetime=timedelta(days=7),
        key_prefix="test:refresh",
        now=lambda: NOW,
        token_factory=lambda: next(secrets),
    )
    issued = await store.issue(USER_ID)

    rotated = await store.rotate(issued.token)

    assert rotated.token == "e" * 64


async def test_redis_failed_rotation_allocation_leaves_source_active():
    token = ["d" * 64]
    store = RedisRefreshTokenStore(
        FakeRedis(decode_responses=True),
        lifetime=timedelta(days=7),
        key_prefix="test:refresh",
        now=lambda: NOW,
        token_factory=lambda: token[0],
    )
    issued = await store.issue(USER_ID)

    with pytest.raises(RefreshTokenStorageError, match="unique"):
        await store.rotate(issued.token)

    token[0] = "e" * 64
    rotated = await store.rotate(issued.token)
    assert rotated.token == "e" * 64


async def test_redis_issue_raises_after_bounded_digest_collisions():
    store = RedisRefreshTokenStore(
        FakeRedis(decode_responses=True),
        lifetime=timedelta(days=7),
        key_prefix="test:refresh",
        now=lambda: NOW,
        token_factory=lambda: "d" * 64,
    )
    await store.issue(USER_ID)

    with pytest.raises(RefreshTokenStorageError, match="unique"):
        await store.issue(USER_ID)


async def test_redis_concurrent_issue_does_not_claim_one_digest_twice(monkeypatch):
    redis = FakeRedis(decode_responses=True)
    real_hgetall = redis.hgetall
    reads = 0
    reads_ready = asyncio.Event()

    async def racing_hgetall(*args, **kwargs):
        nonlocal reads
        result = await real_hgetall(*args, **kwargs)
        reads += 1
        if reads == 2:
            reads_ready.set()
        await reads_ready.wait()
        return result

    monkeypatch.setattr(redis, "hgetall", racing_hgetall)
    stores = [
        RedisRefreshTokenStore(
            redis,
            lifetime=timedelta(days=7),
            key_prefix="test:refresh",
            now=lambda: NOW,
            token_factory=lambda: "d" * 64,
        )
        for _ in range(2)
    ]

    results = await asyncio.gather(
        *(store.issue(USER_ID) for store in stores),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1


async def test_redis_expired_token_is_invalid():
    current_time = [NOW]
    store = RedisRefreshTokenStore(
        FakeRedis(decode_responses=True),
        lifetime=timedelta(days=7),
        key_prefix="test:refresh",
        now=lambda: current_time[0],
        token_factory=lambda: "d" * 64,
    )
    issued = await store.issue(USER_ID)
    current_time[0] = NOW + timedelta(days=8)

    with pytest.raises(InvalidRefreshToken):
        await store.rotate(issued.token)


async def test_redis_malformed_record_is_invalid(redis_store):
    issued = await redis_store.issue(USER_ID)
    digest = sha256(issued.token.encode()).hexdigest()
    await redis_store.redis.hdel(f"test:refresh:token:{digest}", "user_id")

    with pytest.raises(InvalidRefreshToken):
        await redis_store.rotate(issued.token)


async def test_redis_invalid_uuid_metadata_is_invalid(redis_store):
    issued = await redis_store.issue(USER_ID)
    digest = sha256(issued.token.encode()).hexdigest()
    token_key = f"test:refresh:token:{digest}"
    await redis_store.redis.hset(token_key, "family_id", "not-a-uuid")
    await redis_store.redis.sadd("test:refresh:family:not-a-uuid", token_key)

    with pytest.raises(InvalidRefreshToken):
        await redis_store.rotate(issued.token)
    assert await redis_store.redis.hget(token_key, "status") == "active"


async def test_redis_error_is_mapped_to_storage_error(redis_store, monkeypatch):
    async def fail(*args, **kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(redis_store.redis, "hset", fail)
    with pytest.raises(RefreshTokenStorageError) as error:
        await redis_store.issue(USER_ID)
    assert "d" * 64 not in str(error.value)


@pytest.mark.parametrize("operation", ["rotate", "revoke"])
async def test_redis_eval_error_is_mapped_to_storage_error(redis_store, monkeypatch, operation):
    issued = await redis_store.issue(USER_ID)

    async def fail(*args, **kwargs):
        raise TimeoutError("redis unavailable")

    monkeypatch.setattr(redis_store.redis, "eval", fail)
    with pytest.raises(RefreshTokenStorageError) as error:
        await getattr(redis_store, operation)(issued.token)
    assert issued.token not in str(error.value)
