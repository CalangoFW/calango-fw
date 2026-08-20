from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from calango_identity.refresh_tokens import (
    InMemoryRefreshTokenStore,
    InvalidRefreshToken,
    RefreshTokenReuse,
)

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
