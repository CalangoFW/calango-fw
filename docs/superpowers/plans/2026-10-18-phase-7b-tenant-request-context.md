# Phase 7B Tenant Request Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the request's tenant after authentication, carry it in a request-scoped context, and apply it to every PostgreSQL transaction so RLS isolates tenant data.

**Architecture:** Multitenancy registers a second dependency guard (after Identity). Its dependency reads `X-Tenant-ID` (or a custom `TenantResolver`), checks membership in one query and the guard stores the tenant in `request.state` and a `ContextVar`. SQLAlchemy session events apply `set_config('app.current_tenant_id', …, true)` at transaction begin and again before a statement or flush whenever the context tenant differs from the one applied in the current transaction. A pure ASGI middleware resets the context per request.

**Tech Stack:** FastAPI DI, `contextvars`, SQLAlchemy 2 ORM events (`after_begin`, `do_orm_execute`, `before_flush`), PostgreSQL RLS, Pytest with real PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-10-18-phase-7-multitenancy-design.md`

**Depends on:** Phase 7A (ordered guards, plugin package, tenant tables).

## Global Constraints

- One request never observes another request's tenant.
- Unknown, malformed and non-member identifiers produce the identical `403 Tenant access denied`.
- The tenant id is always a bound parameter, never interpolated SQL.
- Run the four repository gates after every task.

## File Structure

| File | Responsibility |
|---|---|
| `packages/calango-core/calango/exceptions/__init__.py` | new `BadRequestError` (400) |
| `.../calango_multitenancy/context.py` | tenant `ContextVar`, `tenant_scope`, `TenantContextMiddleware` |
| `.../calango_multitenancy/database.py` | `install_tenant_listener()` and the session event handlers |
| `.../calango_multitenancy/resolvers.py` | `TenantResolver` protocol, `HeaderTenantResolver` |
| `.../calango_multitenancy/repositories.py` | `TenantRepository.find_member_tenant` |
| `.../calango_multitenancy/dependencies.py` | tenant dependency/resolver factories, guard, `get_current_tenant`, `require_tenant` |
| `.../calango_multitenancy/plugin.py` | wires middleware, listener and guard |
| `conftest.py` (root) | `postgres_app_url` fixture: a non-superuser role owning `public` |

---

### Task 1: `BadRequestError`

**Files:**
- Modify: `packages/calango-core/calango/exceptions/__init__.py`
- Test: `packages/calango-core/tests/test_exceptions.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_bad_request_error_maps_to_400():
    from calango.exceptions import BadRequestError

    error = BadRequestError("Tenant required")
    assert error.status_code == 400
    assert error.error_code == "bad_request"
    assert error.message == "Tenant required"
```

- [ ] **Step 2: Prove RED** — `uv run pytest packages/calango-core/tests/test_exceptions.py -q` → `ImportError`.

- [ ] **Step 3: Implement** (next to `ValidationError`, and in `__all__` if the module defines one)

```python
class BadRequestError(CalangoException):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400, error_code="bad_request")
```

- [ ] **Step 4: Prove GREEN and commit**

```bash
git add packages/calango-core
git commit -m "feat(core): add BadRequestError for 400 responses"
```

### Task 2: Request tenant context

**Files:**
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/context.py`
- Test: `packages/calango-plugins/calango-multitenancy/tests/test_context.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from uuid import uuid4

from calango_multitenancy.context import (
    TenantContextMiddleware,
    current_tenant_id,
    set_current_tenant_id,
    tenant_scope,
)


async def test_tenant_scope_sets_and_restores_the_tenant():
    tenant_id = uuid4()
    assert current_tenant_id() is None
    async with tenant_scope(tenant_id):
        assert current_tenant_id() == tenant_id
    assert current_tenant_id() is None


async def test_middleware_resets_a_tenant_set_inside_the_request():
    tenant_id = uuid4()
    seen: list[object] = []

    async def downstream(scope, receive, send) -> None:
        seen.append(current_tenant_id())
        set_current_tenant_id(tenant_id)
        seen.append(current_tenant_id())

    async def receive():
        return {"type": "http.request"}

    async def send(_message) -> None:
        pass

    middleware = TenantContextMiddleware(downstream)
    async with tenant_scope(uuid4()):
        await middleware({"type": "http"}, receive, send)
    await middleware({"type": "http"}, receive, send)

    assert seen == [None, tenant_id, None, tenant_id]
    assert current_tenant_id() is None
```

- [ ] **Step 2: Prove RED** — `uv run pytest packages/calango-plugins/calango-multitenancy/tests/test_context.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `context.py`**

```python
"""The tenant of the current request or ``tenant_scope``, as a context variable."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import UUID

from starlette.types import ASGIApp, Receive, Scope, Send

_current_tenant_id: ContextVar[UUID | None] = ContextVar(
    "calango_current_tenant_id", default=None
)


def current_tenant_id() -> UUID | None:
    """Return the tenant applied to database work in the current context."""
    return _current_tenant_id.get()


def set_current_tenant_id(tenant_id: UUID | None) -> None:
    """Set the tenant for the rest of the current request (guard use only)."""
    _current_tenant_id.set(tenant_id)


@asynccontextmanager
async def tenant_scope(tenant_id: UUID) -> AsyncIterator[None]:
    """Run trusted server code (jobs, seeds, scripts) as ``tenant_id``.

    No membership check happens here: only use it in code the application owns.
    """
    token = _current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        _current_tenant_id.reset(token)


class TenantContextMiddleware:
    """Start every request without a tenant and restore the caller's afterwards."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = _current_tenant_id.set(None)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_tenant_id.reset(token)
```

- [ ] **Step 4: Prove GREEN and commit**

```bash
git add packages/calango-plugins/calango-multitenancy
git commit -m "feat(multitenancy): add request-scoped tenant context"
```

### Task 3: Transaction tenant setting

**Files:**
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/database.py`
- Test: `packages/calango-plugins/calango-multitenancy/tests/test_database.py`

- [ ] **Step 1: Write the failing tests** (SQLite proves the non-PostgreSQL skip; the PostgreSQL behavior is proven by Task 5's integration tests)

```python
from __future__ import annotations

from uuid import uuid4

from calango_multitenancy.context import tenant_scope
from calango_multitenancy.database import TENANT_SETTING_SQL, install_tenant_listener
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


def test_tenant_setting_uses_a_bound_parameter():
    sql = str(TENANT_SETTING_SQL)
    assert "set_config('app.current_tenant_id', :tenant_id, true)" in sql


def test_install_is_idempotent():
    install_tenant_listener()
    install_tenant_listener()


async def test_listener_skips_non_postgresql_connections():
    install_tenant_listener()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with tenant_scope(uuid4()):
            async with AsyncSession(engine) as session:
                assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Prove RED** — `uv run pytest packages/calango-plugins/calango-multitenancy/tests/test_database.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `database.py`**

```python
"""Apply the context tenant to PostgreSQL transactions for row-level security."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, SessionTransaction

from calango_multitenancy.context import current_tenant_id

TENANT_SETTING_SQL = text("SELECT set_config('app.current_tenant_id', :tenant_id, true)")
_APPLIED_KEY = "calango.multitenancy.applied_tenant"
_installed = False


def _desired_setting() -> str:
    tenant_id = current_tenant_id()
    return "" if tenant_id is None else str(tenant_id)


def _apply(session: Session, connection: Connection) -> None:
    """Set the transaction-local tenant when it differs from what was applied.

    The setting is tracked per root transaction: ``set_config(..., true)`` ends
    with the transaction, and a request's tenant can be resolved after its
    session already began a transaction (e.g. the membership lookup).
    """
    if connection.dialect.name != "postgresql":
        return
    transaction = session.get_transaction()
    desired = _desired_setting()
    applied = session.info.get(_APPLIED_KEY)
    if applied is not None and applied[0] is transaction and applied[1] == desired:
        return
    connection.execute(TENANT_SETTING_SQL, {"tenant_id": desired})
    session.info[_APPLIED_KEY] = (transaction, desired)


def _after_begin(session: Session, _transaction: SessionTransaction, connection: Connection) -> None:
    _apply(session, connection)


def _before_statement(orm_execute_state: Any) -> None:
    session = orm_execute_state.session
    if session.in_transaction():
        _apply(session, session.connection())


def _before_flush(session: Session, _flush_context: Any, _instances: Any) -> None:
    if session.in_transaction():
        _apply(session, session.connection())


def install_tenant_listener() -> None:
    """Register the session events once per process."""
    global _installed
    if _installed:
        return
    event.listen(Session, "after_begin", _after_begin)
    event.listen(Session, "do_orm_execute", _before_statement)
    event.listen(Session, "before_flush", _before_flush)
    _installed = True
```

- [ ] **Step 4: Prove GREEN and commit**

```bash
git add packages/calango-plugins/calango-multitenancy
git commit -m "feat(multitenancy): apply the tenant to every PostgreSQL transaction"
```

### Task 4: Tenant resolution, guard and dependencies

**Files:**
- Create: `.../calango_multitenancy/resolvers.py`
- Create: `.../calango_multitenancy/repositories.py`
- Create: `.../calango_multitenancy/dependencies.py`
- Modify: `.../calango_multitenancy/plugin.py`, `.../calango_multitenancy/__init__.py`
- Test: `packages/calango-plugins/calango-multitenancy/tests/test_resolution.py`

- [ ] **Step 1: Write the failing tests** (no database: the repository is replaced by a stub; real lookups are covered in Task 5)

```python
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from calango_multitenancy.context import current_tenant_id
from calango_multitenancy.dependencies import resolve_tenant, tenant_guard
from calango_multitenancy.resolvers import HeaderTenantResolver
from starlette.requests import Request

from calango.exceptions import AuthorizationError


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


class StubRepository:
    def __init__(self, tenant=None) -> None:
        self.tenant = tenant
        self.calls: list[tuple[str, object]] = []

    async def find_member_tenant(self, identifier: str, user_id):
        self.calls.append((identifier, user_id))
        return self.tenant


async def test_header_resolver_reads_a_trimmed_identifier():
    resolver = HeaderTenantResolver("X-Tenant-ID")
    assert await resolver.resolve(_request({"X-Tenant-ID": "  acme "})) == "acme"
    assert await resolver.resolve(_request({"X-Tenant-ID": "  "})) is None
    assert await resolver.resolve(_request()) is None


async def test_no_identifier_means_no_tenant():
    repository = StubRepository()
    user = SimpleNamespace(id=uuid4())
    assert await resolve_tenant(_request(), user, HeaderTenantResolver(), repository) is None
    assert repository.calls == []


async def test_anonymous_requests_ignore_the_identifier():
    repository = StubRepository()
    request = _request({"X-Tenant-ID": "acme"})
    assert await resolve_tenant(request, None, HeaderTenantResolver(), repository) is None
    assert repository.calls == []


async def test_member_gets_the_tenant():
    tenant = SimpleNamespace(id=uuid4())
    user = SimpleNamespace(id=uuid4())
    repository = StubRepository(tenant)
    request = _request({"X-Tenant-ID": "acme"})
    assert await resolve_tenant(request, user, HeaderTenantResolver(), repository) is tenant
    assert repository.calls == [("acme", user.id)]


@pytest.mark.parametrize("identifier", ["unknown-tenant", "not a slug!", "x" * 500])
async def test_any_unusable_identifier_is_the_same_403(identifier):
    user = SimpleNamespace(id=uuid4())
    request = _request({"X-Tenant-ID": identifier})
    with pytest.raises(AuthorizationError) as denied:
        await resolve_tenant(request, user, HeaderTenantResolver(), StubRepository(None))
    assert denied.value.message == "Tenant access denied"


async def test_guard_stores_the_tenant_on_request_and_context():
    tenant = SimpleNamespace(id=uuid4())
    request = _request()
    await tenant_guard(request, tenant)
    assert request.state.tenant is tenant
    assert current_tenant_id() == tenant.id
```

- [ ] **Step 2: Prove RED** — `uv run pytest packages/calango-plugins/calango-multitenancy/tests/test_resolution.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `resolvers.py`**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from starlette.requests import Request


@runtime_checkable
class TenantResolver(Protocol):
    """Extract the requested tenant identifier (UUID or slug), or ``None``."""

    async def resolve(self, request: Request) -> str | None: ...


class HeaderTenantResolver:
    """Read the tenant identifier from a request header (``X-Tenant-ID``)."""

    def __init__(self, header: str = "X-Tenant-ID") -> None:
        self.header = header

    async def resolve(self, request: Request) -> str | None:
        value = request.headers.get(self.header, "").strip()
        return value or None
```

- [ ] **Step 4: Implement `repositories.py`**

```python
from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from calango_multitenancy.models import Tenant, TenantMembership

SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")


class TenantRepository:
    """Queries over the global tenant tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_member_tenant(self, identifier: str, user_id: UUID) -> Tenant | None:
        """Return the tenant named by ``identifier`` if ``user_id`` belongs to it."""
        try:
            tenant_filter = Tenant.id == UUID(identifier)
        except ValueError:
            if SLUG_PATTERN.fullmatch(identifier) is None:
                return None
            tenant_filter = Tenant.slug == identifier
        statement = (
            select(Tenant)
            .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
            .where(tenant_filter, TenantMembership.user_id == user_id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()
```

- [ ] **Step 5: Implement `dependencies.py`**

```python
"""Tenant resolution for HTTP requests, run as Calango's second request guard."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import aclosing
from typing import Any, Protocol

from calango_identity import User, get_current_user
from calango_identity.dependencies import get_optional_current_user
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from calango.core.database import get_db
from calango.exceptions import AuthorizationError, BadRequestError
from calango_multitenancy.context import set_current_tenant_id
from calango_multitenancy.models import Tenant
from calango_multitenancy.repositories import TenantRepository
from calango_multitenancy.resolvers import TenantResolver


class MemberTenantLookup(Protocol):
    async def find_member_tenant(self, identifier: str, user_id: Any) -> Tenant | None: ...


async def resolve_tenant(
    request: Request,
    user: User | None,
    resolver: TenantResolver,
    repository: MemberTenantLookup,
) -> Tenant | None:
    """Return the requested tenant for a member, ``None`` when none is requested."""
    identifier = await resolver.resolve(request)
    if identifier is None or user is None:
        return None
    tenant = await repository.find_member_tenant(identifier, user.id)
    if tenant is None:
        raise AuthorizationError("Tenant access denied")
    return tenant


def make_tenant_dependency(resolver: TenantResolver) -> Callable[..., Awaitable[Tenant | None]]:
    """FastAPI dependency for API routes; shares the request's database session."""

    async def request_tenant(
        request: Request,
        user: User | None = Depends(get_current_user),  # noqa: B008
        session: AsyncSession = Depends(get_db),  # noqa: B008
    ) -> Tenant | None:
        return await resolve_tenant(request, user, resolver, TenantRepository(session))

    return request_tenant


def make_tenant_resolver(resolver: TenantResolver) -> Callable[[Request], Awaitable[Tenant | None]]:
    """Resolver for Starlette routes and mounts, after Identity's guard ran."""

    async def resolve(request: Request) -> Tenant | None:
        user = await get_optional_current_user(request)
        session_dependency = request.app.database.session
        open_sessions = request.app.dependency_overrides.get(
            session_dependency, session_dependency
        )
        async with aclosing(open_sessions()) as sessions:
            async for session in sessions:
                return await resolve_tenant(request, user, resolver, TenantRepository(session))
        return None

    return resolve


async def tenant_guard(request: Request, tenant: Tenant | None) -> None:
    """Expose the resolved tenant to handlers and to the database listener."""
    request.state.tenant = tenant
    set_current_tenant_id(None if tenant is None else tenant.id)


def get_current_tenant(request: Request) -> Tenant | None:
    """The tenant selected for this request, or ``None``."""
    return getattr(request.state, "tenant", None)


async def require_tenant(
    tenant: Tenant | None = Depends(get_current_tenant),  # noqa: B008
) -> Tenant:
    """The selected tenant; ``400 Tenant required`` when the request names none."""
    if tenant is None:
        raise BadRequestError("Tenant required")
    return tenant
```

- [ ] **Step 6: Wire the plugin**

In `plugin.py`, accept a resolver and register everything:

```python
    def __init__(
        self,
        settings: MultitenancySettings | None = None,
        resolver: TenantResolver | None = None,
    ) -> None:
        self._settings = settings or MultitenancySettings()
        self._resolver = resolver or HeaderTenantResolver(self._settings.TENANT_HEADER)

    def register(self, app: FastAPI) -> None:
        if not isinstance(app, Calango):
            raise TypeError("MultitenancyPlugin requires a Calango application")
        if not identity_is_installed(app):
            raise RuntimeError("Register IdentityPlugin before MultitenancyPlugin")
        install_tenant_listener()
        app.add_middleware(TenantContextMiddleware)
        app.add_dependency_request_guard(
            tenant_guard,
            dependency=make_tenant_dependency(self._resolver),
            resolver=make_tenant_resolver(self._resolver),
        )
```

Export from `__init__.py`: `HeaderTenantResolver`, `TenantResolver`, `get_current_tenant`, `require_tenant`, `tenant_scope`.

- [ ] **Step 7: Prove GREEN, run gates, commit**

```bash
git add packages/calango-plugins/calango-multitenancy
git commit -m "feat(multitenancy): resolve request tenants after authentication"
```

### Task 5: Isolation against real PostgreSQL

**Files:**
- Modify: `conftest.py` (root)
- Create: `packages/calango-plugins/calango-multitenancy/tests/integration/conftest.py`
- Create: `packages/calango-plugins/calango-multitenancy/tests/integration/test_isolation.py`

- [ ] **Step 1: Add the application-role fixture to the root `conftest.py`**

```python
APP_ROLE = "calango_app"


@pytest.fixture
async def postgres_app_url(postgres_url: str) -> AsyncIterator[str]:
    """``postgres_url`` reached as a role without SUPERUSER/BYPASSRLS that owns ``public``.

    Requires ``postgres_url`` to authenticate as a role allowed to create roles
    (the Docker fixture's superuser does).
    """
    engine = create_async_engine(postgres_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'calango_app') THEN "
                    "CREATE ROLE calango_app LOGIN PASSWORD 'calango_app' "
                    "NOSUPERUSER NOBYPASSRLS; "
                    "END IF; END $$"
                )
            )
            await connection.execute(text("ALTER SCHEMA public OWNER TO calango_app"))
    finally:
        await engine.dispose()
    url = make_url(postgres_url).set(username=APP_ROLE, password=APP_ROLE)
    yield url.render_as_string(hide_password=False)
```

(`from sqlalchemy.engine import make_url`.) The role name and password are fixed test values, so the SQL stays static.

- [ ] **Step 2: Write the integration fixtures**

`tests/integration/conftest.py` builds the schema with Alembic (identity + multitenancy revisions, run as the application role), adds a hand-written RLS table (Phase 7C replaces this with `TenantScoped` and `op.enable_tenant_isolation`), and serves an app with two members in two tenants:

```python
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from calango_multitenancy import MultitenancyPlugin, require_tenant
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from calango import Calango
from calango.config import CalangoSettings, DatabaseSettings, SecuritySettings
from calango.core.database import get_db
from calango_cli.migrations import MigrationResources, version_locations

PASSWORD = "SecurePassword123!"
SCRIPT_LOCATION = Path(__file__).parents[1] / "alembic"
ISOLATED = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
NOTES_DDL = (
    "CREATE TABLE notes ("
    "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
    "body text NOT NULL, "
    "tenant_id uuid NOT NULL "
    "DEFAULT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid "
    "REFERENCES tenants (id))",
    "ALTER TABLE notes ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE notes FORCE ROW LEVEL SECURITY",
    "CREATE POLICY calango_tenant_isolation ON notes "
    "USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid) "
    "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)",
)


def _upgrade(url: str, locations: tuple[Path, ...]) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    config.set_main_option("version_locations", os.pathsep.join(map(str, locations)))
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "heads")


@pytest.fixture
async def tenant_database(postgres_app_url: str, identity_plugin) -> str:
    with MigrationResources() as resources:
        locations = version_locations(
            (*identity_plugin.migrations(), *MultitenancyPlugin().migrations()),
            resources=resources,
        )
        await asyncio.to_thread(_upgrade, postgres_app_url, locations)
    engine = create_async_engine(postgres_app_url)
    try:
        async with engine.begin() as connection:
            for statement in NOTES_DDL:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()
    return postgres_app_url


def build_tenant_app(database_url: str, identity_plugin, pool_size: int = 1) -> Calango:
    """``pool_size=1`` forces connection reuse between sequential requests."""
    app = Calango(
        settings=CalangoSettings(
            database=DatabaseSettings(URL=database_url, POOL_SIZE=pool_size, MAX_OVERFLOW=0),
            security=SecuritySettings(SECRET_KEY="integration-secret"),
        )
    )

    @app.get("/notes")
    async def list_notes(session: AsyncSession = Depends(get_db)):  # noqa: B008
        rows = await session.execute(text("SELECT body FROM notes ORDER BY body"))
        return {"notes": list(rows.scalars())}

    @app.post("/notes")
    async def add_note(body: str, session: AsyncSession = Depends(get_db)):  # noqa: B008
        await session.execute(text("INSERT INTO notes (body) VALUES (:body)"), {"body": body})
        await session.commit()
        rows = await session.execute(text("SELECT body FROM notes ORDER BY body"))
        return {"notes": list(rows.scalars())}

    @app.post("/notes/into")
    async def add_note_into(
        body: str,
        tenant_id: str,
        session: AsyncSession = Depends(get_db),  # noqa: B008
    ):
        try:
            await session.execute(
                text("INSERT INTO notes (body, tenant_id) VALUES (:body, :tenant_id)"),
                {"body": body, "tenant_id": tenant_id},
            )
            await session.commit()
        except DBAPIError:
            await session.rollback()
            return {"rejected": True}
        return {"rejected": False}

    @app.get("/required")
    async def required(tenant=Depends(require_tenant)):  # noqa: B008
        return {"slug": tenant.slug}

    app.include_plugin(identity_plugin)
    app.include_plugin(MultitenancyPlugin())
    return app


@dataclass
class Member:
    headers: dict[str, str]
    tenant_id: str
    slug: str


@dataclass
class TenantWorld:
    app: Calango
    client: AsyncClient
    alice: Member
    bob: Member


async def _member(client: AsyncClient, database_url: str, email: str, slug: str) -> Member:
    registered = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert registered.status_code == 201, registered.text
    login = await client.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            tenant_id = (
                await connection.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name) "
                        "VALUES (gen_random_uuid(), :slug, :slug) RETURNING id"
                    ),
                    {"slug": slug},
                )
            ).scalar_one()
            await connection.execute(
                text(
                    "INSERT INTO tenant_memberships (id, tenant_id, user_id, role) "
                    "VALUES (gen_random_uuid(), :tenant_id, :user_id, 'owner')"
                ),
                {"tenant_id": tenant_id, "user_id": registered.json()["id"]},
            )
    finally:
        await engine.dispose()
    token = login.json()["access_token"]
    return Member({"Authorization": f"Bearer {token}"}, str(tenant_id), slug)


@asynccontextmanager
async def _serve_world(database_url: str, identity_plugin, pool_size: int):
    app = build_tenant_app(database_url, identity_plugin, pool_size)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            alice = await _member(client, database_url, "alice@example.com", "alice-co")
            bob = await _member(client, database_url, "bob@example.com", "bob-co")
            yield TenantWorld(app, client, alice, bob)


@pytest.fixture
async def tenant_world(tenant_database: str, identity_plugin) -> AsyncIterator[TenantWorld]:
    async with _serve_world(tenant_database, identity_plugin, pool_size=1) as world:
        yield world


@pytest.fixture
async def tenant_world_pool(tenant_database: str, identity_plugin) -> AsyncIterator[TenantWorld]:
    """Same world with five pooled connections, so requests really overlap."""
    async with _serve_world(tenant_database, identity_plugin, pool_size=5) as world:
        yield world
```

Add `from contextlib import asynccontextmanager` to the imports.

- [ ] **Step 3: Write the isolation tests**

`tests/integration/test_isolation.py`:

```python
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from calango.core.database import get_db

pytestmark = pytest.mark.integration


def as_member(member, *, tenant: str | None = None) -> dict[str, str]:
    return {**member.headers, "X-Tenant-ID": tenant or member.slug}


async def test_members_see_and_create_only_their_tenant_rows(tenant_world):
    client, alice, bob = tenant_world.client, tenant_world.alice, tenant_world.bob
    await client.post("/notes", params={"body": "alice-1"}, headers=as_member(alice))
    await client.post("/notes", params={"body": "bob-1"}, headers=as_member(bob))

    alice_view = await client.get("/notes", headers=as_member(alice))
    bob_view = await client.get("/notes", headers=as_member(bob, tenant=bob.tenant_id))

    assert alice_view.json() == {"notes": ["alice-1"]}
    assert bob_view.json() == {"notes": ["bob-1"]}


async def test_writing_into_another_tenant_is_rejected_by_the_database(tenant_world):
    client, alice, bob = tenant_world.client, tenant_world.alice, tenant_world.bob
    response = await client.post(
        "/notes/into",
        params={"body": "smuggled", "tenant_id": bob.tenant_id},
        headers=as_member(alice),
    )
    assert response.json() == {"rejected": True}
    bob_view = await client.get("/notes", headers=as_member(bob))
    assert bob_view.json() == {"notes": []}


@pytest.mark.parametrize("tenant", ["bob-co", "missing-co", "not a slug!"])
async def test_foreign_unknown_and_malformed_tenants_get_the_same_403(tenant_world, tenant):
    response = await tenant_world.client.get(
        "/notes", headers=as_member(tenant_world.alice, tenant=tenant)
    )
    assert response.status_code == 403
    assert response.json()["message"] == "Tenant access denied"


async def test_without_a_tenant_rows_are_invisible_and_required_is_400(tenant_world):
    client, alice = tenant_world.client, tenant_world.alice
    await client.post("/notes", params={"body": "alice-1"}, headers=as_member(alice))

    assert (await client.get("/notes", headers=alice.headers)).json() == {"notes": []}
    required = await client.get("/required", headers=alice.headers)
    assert required.status_code == 400
    assert required.json()["message"] == "Tenant required"


async def test_tenant_survives_a_commit_inside_the_request(tenant_world):
    response = await tenant_world.client.post(
        "/notes", params={"body": "after-commit"}, headers=as_member(tenant_world.alice)
    )
    assert response.json() == {"notes": ["after-commit"]}


async def test_reused_pool_connection_does_not_leak_the_previous_tenant(tenant_world):
    client, alice = tenant_world.client, tenant_world.alice
    await client.post("/notes", params={"body": "alice-1"}, headers=as_member(alice))
    # POOL_SIZE=1: the next request reuses the same database connection.
    assert (await client.get("/notes", headers=alice.headers)).json() == {"notes": []}


async def test_concurrent_requests_for_different_tenants_never_cross(tenant_world_pool):
    client = tenant_world_pool.client
    alice, bob = tenant_world_pool.alice, tenant_world_pool.bob
    await client.post("/notes", params={"body": "alice-1"}, headers=as_member(alice))
    await client.post("/notes", params={"body": "bob-1"}, headers=as_member(bob))

    responses = await asyncio.gather(
        *(client.get("/notes", headers=as_member(member)) for member in (alice, bob) * 10)
    )
    views = [response.json()["notes"] for response in responses]
    assert views == [["alice-1"], ["bob-1"]] * 10


async def test_tenant_applies_when_lookup_and_handler_share_one_session(tenant_world):
    app, client, alice = tenant_world.app, tenant_world.client, tenant_world.alice
    await client.post("/notes", params={"body": "alice-1"}, headers=as_member(alice))
    engine = create_async_engine(str(app.settings.database.URL))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as shared:

            async def same_session():
                yield shared

            for dependency in (get_db, app.database.session):
                app.dependency_overrides[dependency] = same_session
            response = await client.get("/notes", headers=as_member(alice))
            app.dependency_overrides.clear()
    finally:
        await engine.dispose()
    assert response.json() == {"notes": ["alice-1"]}
```

- [ ] **Step 4: Run and make GREEN**

Run: `uv run pytest packages/calango-plugins/calango-multitenancy/tests/integration -q`
Expected: PASS. If a test fails, fix production code (Tasks 2–4) under its failing assertion; do not weaken the test.

- [ ] **Step 5: Run all gates and commit**

```bash
git add conftest.py packages/calango-plugins/calango-multitenancy
git commit -m "test(multitenancy): prove tenant isolation on real PostgreSQL"
```
