# Calango Identity Phase 6 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Phase 6 with opaque Redis-backed refresh-token rotation, reuse detection, logout revocation, isolated tests, and finished package documentation.

**Architecture:** Keep RS256 JWTs as short-lived access tokens and introduce a focused `RefreshTokenStore` boundary for opaque refresh tokens. A Redis implementation stores only SHA-256 digests and performs rotation atomically; the auth router owns HTTP translation while the plugin owns dependency wiring and Redis lifecycle.

**Tech Stack:** Python 3.12, FastAPI 0.115+, FastAPI-Users 13+, Pydantic v2, redis-py asyncio 5.2+, fakeredis 2.26+, Pytest, Ruff, Ty.

**Spec:** `docs/superpowers/specs/2026-05-28-calango-identity-design.md`

## Global Constraints

- Minimum Python is 3.12.
- Access tokens remain JWT RS256 with a 15-minute default lifetime.
- Refresh tokens are opaque, have a 7-day default absolute lifetime, and never extend their family expiration during rotation.
- Persist only SHA-256 token digests; never persist or log raw refresh tokens or their digests.
- A reused token revokes its entire family.
- Rotation must be atomic, so at most one concurrent use of a token succeeds.
- Invalid token states share one `401` response; Redis failures fail closed with `503`.
- Logout is idempotent for a well-formed token from an already revoked family.
- Do not add SQL tables or migrations for refresh tokens.
- Follow TDD and run Ruff, Ruff format, Ty, and Pytest after every code modification.
- Phase 7 multitenancy is out of scope.

## File Map

- Create `calango_identity/refresh_tokens.py`: token records, domain errors, store protocol, Redis store, and test in-memory store.
- Create `tests/test_refresh_tokens.py`: lifecycle, hashing, TTL, reuse, revocation, failure, and concurrency tests.
- Modify `calango_identity/router.py`: canonical login, refresh, and logout endpoints and HTTP error translation.
- Modify `calango_identity/plugin.py`: Redis client/store construction and router wiring.
- Modify `calango_identity/schemas.py`: refresh request and token response schemas.
- Modify `calango_identity/security.py`: explicit access-token creation helper.
- Modify `calango_identity/settings.py`: refresh-token key namespace setting.
- Modify `calango_identity/__init__.py`: export the stable refresh-token interfaces.
- Modify `tests/test_auth_router.py`: endpoint-level login/refresh/logout behavior.
- Modify `tests/test_plugin.py`: production dependency wiring.
- Create `packages/calango-core/tests/conftest.py`: isolate core settings tests from host environment.
- Modify package READMEs, `ROADMAP.md`, and root `README.md`: document and mark Phase 6 complete.

---

### Task 1: Isolate core settings tests from the host environment

**Files:**
- Create: `packages/calango-core/tests/conftest.py`
- Test: `packages/calango-core/tests/test_config.py`

**Interfaces:**
- Consumes: Pytest's `monkeypatch` fixture.
- Produces: an autouse fixture that removes only Calango's unprefixed top-level settings keys during core tests.

- [ ] **Step 1: Reproduce the current environmental failure**

Run:

```bash
DEBUG=release uv run pytest packages/calango-core/tests/test_config.py::TestCalangoSettings::test_defaults_de_aplicacao -v
```

Expected: FAIL with `DEBUG Input should be a valid boolean`.

- [ ] **Step 2: Add the test-environment isolation fixture**

Create `packages/calango-core/tests/conftest.py`:

```python
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_calango_settings_from_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Host application settings must not leak into core unit tests."""
    for name in ("APP_NAME", "VERSION", "ENV", "DEBUG"):
        monkeypatch.delenv(name, raising=False)
```

- [ ] **Step 3: Verify the regression is fixed under the hostile value**

Run:

```bash
DEBUG=release uv run pytest packages/calango-core/tests/test_config.py packages/calango-core/tests/test_app.py -v
```

Expected: PASS.

- [ ] **Step 4: Run local quality gates**

Run:

```bash
uv run ruff check packages/calango-core/tests/conftest.py
uv run ruff format --check packages/calango-core/tests/conftest.py
uv run ty check packages/calango-core/tests/conftest.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add packages/calango-core/tests/conftest.py
git commit -m "test(core): isolate settings from host environment"
```

---

### Task 2: Define the refresh-token domain and in-memory contract tests

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/refresh_tokens.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/settings.py`

**Interfaces:**
- Consumes: `IdentitySettings.REFRESH_TOKEN_EXPIRE_DAYS`.
- Produces: `RefreshTokenPair`, `RefreshTokenStore`, `InMemoryRefreshTokenStore`, `InvalidRefreshToken`, `RefreshTokenReuse`, and `RefreshTokenStorageError`.

- [ ] **Step 1: Write failing lifecycle tests**

Create `tests/test_refresh_tokens.py` with deterministic time and token factories:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py -v
```

Expected: FAIL because `calango_identity.refresh_tokens` does not exist.

- [ ] **Step 3: Implement the domain types and store protocol**

In `refresh_tokens.py`, define these exact public interfaces:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID, uuid4


class InvalidRefreshToken(Exception):
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
```

Implement `InMemoryRefreshTokenStore` with an `asyncio.Lock`, a `records` mapping keyed by `sha256(token.encode()).hexdigest()`, and injected `now` and `token_factory`. `issue()` creates a UUID family and absolute expiry; `rotate()` changes the old status to `USED`, creates a new digest in the same family, and never extends expiry; reuse marks every family record `REVOKED`; `revoke()` accepts a known used or revoked token idempotently. Reject malformed tokens shorter than 43 characters before hashing.

- [ ] **Step 4: Add the Redis namespace setting**

Add to `IdentitySettings`:

```python
REFRESH_TOKEN_KEY_PREFIX: str = "calango:identity:refresh"
```

- [ ] **Step 5: Run tests and quality gates**

Run:

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py -v
uv run ruff check packages/calango-plugins/calango-identity
uv run ruff format --check packages/calango-plugins/calango-identity
uv run ty check packages/calango-plugins/calango-identity
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugins/calango-identity/calango_identity/refresh_tokens.py packages/calango-plugins/calango-identity/calango_identity/settings.py packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py
git commit -m "feat(identity): define refresh token lifecycle"
```

---

### Task 3: Implement atomic Redis refresh-token storage

**Files:**
- Modify: `packages/calango-plugins/calango-identity/calango_identity/refresh_tokens.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py`

**Interfaces:**
- Consumes: the `RefreshTokenStore` contract from Task 2 and an async Redis client supporting `hset`, `hgetall`, `expireat`, and `eval`.
- Produces: `RedisRefreshTokenStore(redis, lifetime, key_prefix, now, token_factory)` implementing that contract.

- [ ] **Step 1: Add failing Redis behavior tests**

Append tests using `fakeredis.aioredis.FakeRedis(decode_responses=True)`:

```python
from fakeredis.aioredis import FakeRedis

from calango_identity.refresh_tokens import RedisRefreshTokenStore, RefreshTokenStorageError


@pytest.fixture
def redis_store():
    redis = FakeRedis(decode_responses=True)
    secrets = iter(("d" * 64, "e" * 64, "f" * 64))
    return RedisRefreshTokenStore(
        redis,
        lifetime=timedelta(days=7),
        key_prefix="test:refresh",
        now=lambda: NOW,
        token_factory=lambda: next(secrets),
    )


async def test_redis_store_never_uses_raw_token_as_key(redis_store):
    issued = await redis_store.issue(USER_ID)
    keys = await redis_store.redis.keys("*")
    assert all(issued.token not in key for key in keys)


async def test_redis_rotation_preserves_absolute_expiry(redis_store):
    issued = await redis_store.issue(USER_ID)
    rotated = await redis_store.rotate(issued.token)
    assert rotated.expires_at == issued.expires_at


async def test_redis_error_is_mapped_to_storage_error(redis_store, monkeypatch):
    async def fail(*args, **kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(redis_store.redis, "hset", fail)
    with pytest.raises(RefreshTokenStorageError):
        await redis_store.issue(USER_ID)
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run:

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py -k redis -v
```

Expected: FAIL because `RedisRefreshTokenStore` is missing.

- [ ] **Step 3: Implement the Redis key model and issuance**

Use exact key forms:

```python
def _token_key(self, digest: str) -> str:
    return f"{self.key_prefix}:token:{digest}"

def _family_key(self, family_id: UUID) -> str:
    return f"{self.key_prefix}:family:{family_id}"
```

Store `user_id`, `family_id`, `expires_at` as an integer UTC timestamp, and `status` in the token hash. Store token keys in a Redis set per family. Apply `expireat` with the same absolute timestamp to both keys. Catch `redis.exceptions.RedisError`, `ConnectionError`, and `TimeoutError` at the boundary and raise `RefreshTokenStorageError` without including token material.

- [ ] **Step 4: Implement atomic rotation and family revocation**

Use a Lua script invoked by `EVAL` that:

1. Reads the old token status and family.
2. Returns `missing`, `revoked`, or `used` without creating a new record.
3. On `used`, iterates the family set and marks every member `revoked`.
4. On `active`, marks the old record `used`, creates the new digest record, adds it to the family set, and applies the original `expires_at` to both new keys.

Map `used` to `RefreshTokenReuse`; map `missing`, `revoked`, malformed, or expired to `InvalidRefreshToken`. Use a second Lua script for idempotent family revocation. Keep script constants private at module level and add comments documenting their return codes.

- [ ] **Step 5: Verify Redis lifecycle, reuse, and concurrency**

Run:

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py -v
uv run ruff check packages/calango-plugins/calango-identity
uv run ruff format --check packages/calango-plugins/calango-identity
uv run ty check packages/calango-plugins/calango-identity
```

Expected: all pass, including the in-memory and Redis implementations against the same lifecycle expectations.

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugins/calango-identity/calango_identity/refresh_tokens.py packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py
git commit -m "feat(identity): add atomic Redis refresh token store"
```

---

### Task 4: Add canonical login, refresh, and logout endpoints

**Files:**
- Modify: `packages/calango-plugins/calango-identity/calango_identity/schemas.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/security.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/router.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_auth_router.py`

**Interfaces:**
- Consumes: `RefreshTokenStore`; `UserManager.authenticate(credentials)`; `JWTStrategy.write_token(user)`.
- Produces: `TokenResponse`, `RefreshTokenInput`, and `make_auth_router(settings, get_db, refresh_store)` with `/auth/login`, `/auth/refresh`, and `/auth/logout`.

- [ ] **Step 1: Replace the login assertion with the approved contract and add refresh/logout tests**

Update `test_auth_router.py` so its fixture injects an `InMemoryRefreshTokenStore`, then assert:

```python
async def test_login_returns_access_and_refresh_tokens(client):
    await register_user(client, "login@example.com")
    response = await client.post(
        "/auth/login",
        data={"username": "login@example.com", "password": "SecurePassword123!"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["expires_in"] == 900
    assert response.json()["access_token"]
    assert response.json()["refresh_token"]


async def test_refresh_rotates_both_tokens(client):
    login = await login_user(client, "refresh@example.com")
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert response.status_code == 200
    assert response.json()["refresh_token"] != login["refresh_token"]
    assert response.json()["access_token"]


async def test_refresh_reuse_returns_uniform_401_and_revokes_family(client):
    login = await login_user(client, "reuse@example.com")
    rotated = await client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    reused = await client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    family = await client.post("/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]})
    assert reused.status_code == family.status_code == 401
    assert reused.json()["error"] == family.json()["error"] == "authentication_error"
    assert reused.json()["message"] == family.json()["message"] == "Invalid refresh token"


async def test_logout_is_idempotent(client):
    login = await login_user(client, "logout@example.com")
    body = {"refresh_token": login["refresh_token"]}
    assert (await client.post("/auth/logout", json=body)).status_code == 204
    assert (await client.post("/auth/logout", json=body)).status_code == 204
```

Add local `register_user` and `login_user` helpers with the exact URLs above.

- [ ] **Step 2: Run tests to verify the new contract fails**

Run:

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_auth_router.py -v
```

Expected: FAIL because `/auth/login`, refresh, and logout are not registered.

- [ ] **Step 3: Add request and response schemas**

Add to `schemas.py`:

```python
from pydantic import BaseModel, Field


class RefreshTokenInput(BaseModel):
    refresh_token: str = Field(min_length=43, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str
    expires_in: int
```

- [ ] **Step 4: Add an explicit access-token helper**

Add to `security.py`:

```python
async def create_access_token(user: User, settings: IdentitySettings) -> str:
    return await make_jwt_strategy(settings).write_token(user)
```

Import `User` from `calango_identity.models`.

- [ ] **Step 5: Implement the three endpoints**

Change `make_auth_router` to accept `refresh_store: RefreshTokenStore`. Keep the FastAPI-Users register, reset-password, and users routers, but do not register its generated `/auth/jwt/login` router.

Implement `/auth/login` using `OAuth2PasswordRequestForm`, `UserManager.authenticate`, `create_access_token`, and `refresh_store.issue(user.id)`. Implement `/auth/refresh` by rotating first, loading the user by UUID through the manager, rejecting missing/inactive users with the uniform `401`, then creating the access JWT. Implement `/auth/logout` with status 204.

Use Calango exceptions so plugin errors retain the framework's normal error envelope:

```python
from calango.exceptions import AuthenticationError, ServiceUnavailableError


def _translate_refresh_error(exc: Exception) -> AuthenticationError | ServiceUnavailableError:
    if isinstance(exc, RefreshTokenStorageError):
        return ServiceUnavailableError("Authentication service unavailable")
    return AuthenticationError("Invalid refresh token")
```

Use a `Calango` instance in endpoint tests so these exceptions are rendered through
the framework handler. Do not include exception strings in responses or logs. Add
response models and `status_code=204` explicitly.

- [ ] **Step 6: Add unavailable-store endpoint tests**

Define a test double whose three methods raise `RefreshTokenStorageError`, inject it into a separate app fixture, and verify login, refresh, and logout each return `503` with identical non-sensitive detail.

- [ ] **Step 7: Run endpoint tests and quality gates**

Run:

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_auth_router.py packages/calango-plugins/calango-identity/tests/test_refresh_tokens.py -v
uv run ruff check packages/calango-plugins/calango-identity
uv run ruff format --check packages/calango-plugins/calango-identity
uv run ty check packages/calango-plugins/calango-identity
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/calango-plugins/calango-identity/calango_identity/schemas.py packages/calango-plugins/calango-identity/calango_identity/security.py packages/calango-plugins/calango-identity/calango_identity/router.py packages/calango-plugins/calango-identity/tests/test_auth_router.py
git commit -m "feat(identity): rotate refresh tokens through auth endpoints"
```

---

### Task 5: Wire Redis storage through IdentityPlugin

**Files:**
- Modify: `packages/calango-plugins/calango-identity/calango_identity/plugin.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/__init__.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_plugin.py`

**Interfaces:**
- Consumes: `RedisRefreshTokenStore` and `make_auth_router(..., refresh_store)`.
- Produces: `IdentityPlugin(settings=None, refresh_store=None)` with production Redis defaults and test injection.

- [ ] **Step 1: Write failing plugin wiring tests**

Add tests that inject `InMemoryRefreshTokenStore` and assert the registered app exposes `/auth/login`, `/auth/refresh`, and `/auth/logout`. Add a monkeypatched `redis.asyncio.from_url` assertion for the default path:

```python
def test_plugin_builds_redis_store_from_settings(monkeypatch, identity_settings):
    sentinel = object()
    monkeypatch.setattr("calango_identity.plugin.redis.from_url", lambda *args, **kwargs: sentinel)
    plugin = IdentityPlugin(settings=identity_settings)
    assert plugin.refresh_store.redis is sentinel
```

- [ ] **Step 2: Run the focused test to verify failure**

Run:

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_plugin.py -v
```

Expected: FAIL because the plugin does not accept or expose a refresh store.

- [ ] **Step 3: Implement dependency wiring**

In `plugin.py`, import `redis.asyncio as redis`. Extend the constructor:

```python
def __init__(
    self,
    settings: IdentitySettings | None = None,
    refresh_store: RefreshTokenStore | None = None,
) -> None:
```

When no store is supplied, create a decoded async client with:

```python
client = redis.from_url(self._settings.REDIS_URL, decode_responses=True)
self.refresh_store = RedisRefreshTokenStore(
    client,
    lifetime=timedelta(days=self._settings.REFRESH_TOKEN_EXPIRE_DAYS),
    key_prefix=self._settings.REFRESH_TOKEN_KEY_PREFIX,
)
```

Pass `self.refresh_store` to `make_auth_router`. Preserve the existing SlowAPI limiter and exception handler registration.

- [ ] **Step 4: Export stable interfaces**

Add `RefreshTokenStore` and `RedisRefreshTokenStore` to imports and `__all__` in `calango_identity/__init__.py`. Do not export the in-memory test implementation.

- [ ] **Step 5: Run plugin and complete identity tests**

Run:

```bash
uv run pytest packages/calango-plugins/calango-identity/tests -v
uv run ruff check packages/calango-plugins/calango-identity
uv run ruff format --check packages/calango-plugins/calango-identity
uv run ty check packages/calango-plugins/calango-identity
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugins/calango-identity/calango_identity/plugin.py packages/calango-plugins/calango-identity/calango_identity/__init__.py packages/calango-plugins/calango-identity/tests/test_plugin.py
git commit -m "feat(identity): wire Redis refresh storage into plugin"
```

---

### Task 6: Complete public documentation and Phase 6 status

**Files:**
- Modify: `packages/calango-plugin-base/README.md`
- Modify: `packages/calango-plugins/calango-identity/README.md`
- Modify: `ROADMAP.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: final public endpoint and plugin APIs from Tasks 4 and 5.
- Produces: installation, configuration, endpoint, security, and plugin-author guidance matching shipped behavior.

- [ ] **Step 1: Replace both placeholder READMEs**

Document in `calango-plugin-base/README.md`:

- installation with `uv add calango-plugin-base`;
- all `PluginBase` attributes and methods;
- a complete minimal conforming plugin;
- registration through `Calango.include_plugin()`.

Document in `calango-identity/README.md`:

- installation and `IdentityPlugin` registration;
- RSA key and Redis environment variables;
- `/auth/login`, `/auth/refresh`, `/auth/logout`, registration, reset-password, and users endpoints;
- exact login form and refresh/logout JSON examples;
- rotation, reuse revocation, absolute seven-day lifetime, and Redis fail-closed behavior;
- `@public` and `require_permission` examples;
- a warning never to log or persist raw refresh tokens.

- [ ] **Step 2: Update roadmap and root status**

Change Phase 6 to `✅ Done`, remove “refresh-token rotation pending,” and add the completed Identity component to the root README status table. Ensure endpoint paths use `/auth/login`, `/auth/refresh`, and `/auth/logout` consistently.

- [ ] **Step 3: Scan documentation for stale claims**

Run:

```bash
rg -n "Coming soon|refresh-token rotation pending|/auth/jwt/login|/auth/jwt" README.md ROADMAP.md packages/calango-plugin-base/README.md packages/calango-plugins/calango-identity/README.md
```

Expected: no matches in these files.

- [ ] **Step 4: Commit**

```bash
git add README.md ROADMAP.md packages/calango-plugin-base/README.md packages/calango-plugins/calango-identity/README.md
git commit -m "docs: mark identity Phase 6 complete"
```

---

### Task 7: Run the Phase 6 completion gates

**Files:**
- Modify only files required to fix failures caused by Tasks 1–6.
- Test: all package test suites.

**Interfaces:**
- Consumes: the complete Phase 6 implementation.
- Produces: a clean worktree with all repository gates passing and an evidence-backed completion report.

- [ ] **Step 1: Run lint and formatting**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: `All checks passed!` and all files formatted. If formatting fails, run `uv run ruff format <reported-files>`, rerun both checks, and commit only those mechanical changes.

- [ ] **Step 2: Run static type checking**

Run:

```bash
uv run ty check packages/
```

Expected: all checks pass. Fix real type errors at the source; use `# ty: ignore[rule]` only for the limitations listed in `CLAUDE.md`, with a one-line explanation.

- [ ] **Step 3: Run the complete suite under normal and hostile environments**

Run:

```bash
uv run pytest packages/
DEBUG=release uv run pytest packages/
```

Expected: both runs pass. The hostile run proves core tests no longer consume the host's invalid `DEBUG` value.

- [ ] **Step 4: Run security checks when available**

Run:

```bash
uv run calango check:security
```

Expected: no SCA or SAST findings. If an external scanner executable is unavailable, record the exact missing executable in the completion report; do not claim that gate passed.

- [ ] **Step 5: Verify repository and Phase 6 status**

Run:

```bash
git status --short
git log -8 --oneline
rg -n "Phase 6.*Done|calango-identity" ROADMAP.md README.md
```

Expected: clean worktree, coherent focused commits, and Phase 6 marked done.

- [ ] **Step 6: Commit any gate-driven fixes**

If and only if the gates required source changes:

```bash
git add <only-the-files-fixed-for-the-gates>
git commit -m "fix(identity): resolve Phase 6 verification findings"
```

Otherwise, do not create an empty commit.
