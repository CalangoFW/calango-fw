# Phase 7A Ordered Guards and Tenant Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let several dependency request guards compose in order, and create the `calango-multitenancy` package with its global `tenants` and `tenant_memberships` tables and migration.

**Architecture:** The single framework-owned guard boundary becomes a composite FastAPI dependency with one `Depends(...)` per registration, so FastAPI resolves (and caches, and overrides) each registered dependency normally. External boundaries resolve and run each registration in order. The new plugin package mirrors `calango-identity`: wheel-safe Alembic versions, an entry point, and models on `calango.db.Base`.

**Tech Stack:** FastAPI 0.141 DI, `inspect.Signature`, SQLAlchemy 2, Alembic, Pytest, real PostgreSQL via the root `postgres_url` fixture.

**Spec:** `docs/superpowers/specs/2026-10-18-phase-7-multitenancy-design.md`

## Global Constraints

- Existing single-guard behavior and every current test stay green.
- Registration after startup still raises `RuntimeError`.
- The plugin package follows `calango-identity`'s layout and quality gates.
- Run after every task: `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check packages/`, `uv run pytest packages/ -q`.

## File Structure

| File | Responsibility |
|---|---|
| `packages/calango-core/calango/core/guards.py` | registrations tuple, composite boundary dependency, ordered runners |
| `packages/calango-core/calango/core/app.py` | `add_dependency_request_guard` appends instead of refusing |
| `packages/calango-plugins/calango-identity/calango_identity/dependencies.py` | `identity_is_installed(app)` helper |
| `packages/calango-plugins/calango-multitenancy/pyproject.toml` | package metadata, entry point |
| `.../calango_multitenancy/__init__.py` | public exports (grows in 7b–7d) |
| `.../calango_multitenancy/settings.py` | `MultitenancySettings` (`MULTITENANCY__TENANT_HEADER`) |
| `.../calango_multitenancy/models.py` | `Tenant`, `TenantMembership` |
| `.../calango_multitenancy/migrations/versions/0001_multitenancy.py` | revision creating both tables |
| `.../calango_multitenancy/plugin.py` | `MultitenancyPlugin` (contract methods; `register` grows in 7b) |

---

### Task 1: Ordered dependency request guards

**Files:**
- Modify: `packages/calango-core/calango/core/guards.py`
- Modify: `packages/calango-core/calango/core/app.py`
- Test: `packages/calango-core/tests/test_guards.py`

- [ ] **Step 1: Write the failing tests** (append to `test_guards.py`; `Depends`, `Request`, `JSONResponse`, `TestClient` are already imported there)

```python
def test_dependency_guards_run_in_registration_order(app: Calango) -> None:
    calls: list[tuple[str, object]] = []

    async def first_dependency(_request: Request) -> str:
        return "first"

    async def second_dependency(_request: Request) -> str:
        return "second"

    async def first_guard(_request: Request, context: object) -> None:
        calls.append(("first", context))

    async def second_guard(_request: Request, context: object) -> None:
        calls.append(("second", context))

    app.add_dependency_request_guard(
        first_guard, dependency=first_dependency, resolver=first_dependency
    )
    app.add_dependency_request_guard(
        second_guard, dependency=second_dependency, resolver=second_dependency
    )

    @app.get("/api")
    async def api_route() -> dict[str, bool]:
        return {"ok": True}

    async def raw_route(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app.add_route("/raw", raw_route)
    client = TestClient(app)

    assert client.get("/api").status_code == 200
    assert client.get("/raw").status_code == 200
    assert calls == [
        ("first", "first"),
        ("second", "second"),
        ("first", "first"),
        ("second", "second"),
    ]


def test_later_external_resolver_sees_state_from_earlier_guard(app: Calango) -> None:
    seen: list[object] = []

    async def user_context(_request: Request) -> str:
        return "alice"

    async def store_user(request: Request, user: object) -> None:
        request.scope["test.user"] = user

    async def tenant_context(request: Request) -> str:
        return f"tenant-of-{request.scope.get('test.user')}"

    async def record_tenant(_request: Request, tenant: object) -> None:
        seen.append(tenant)

    app.add_dependency_request_guard(store_user, dependency=user_context, resolver=user_context)
    app.add_dependency_request_guard(
        record_tenant, dependency=tenant_context, resolver=tenant_context
    )

    async def raw_route(_request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app.add_route("/raw", raw_route)

    assert TestClient(app).get("/raw").status_code == 200
    assert seen == ["tenant-of-alice"]


def test_shared_sub_dependency_resolves_once_across_guards(app: Calango) -> None:
    resolutions: list[str] = []

    async def current_user() -> str:
        resolutions.append("user")
        return "alice"

    async def identity_context(user: str = Depends(current_user)) -> str:  # noqa: B008
        return user

    async def tenant_context(user: str = Depends(current_user)) -> str:  # noqa: B008
        return f"{user}-tenant"

    async def accept(_request: Request, _context: object) -> None:
        pass

    async def unused_resolver(_request: Request) -> None:
        return None

    app.add_dependency_request_guard(
        accept, dependency=identity_context, resolver=unused_resolver
    )
    app.add_dependency_request_guard(accept, dependency=tenant_context, resolver=unused_resolver)

    @app.get("/api")
    async def api_route() -> dict[str, bool]:
        return {"ok": True}

    assert TestClient(app).get("/api").status_code == 200
    assert resolutions == ["user"]


def test_public_override_of_later_guard_dependency_supplies_its_context(app: Calango) -> None:
    contexts: list[object] = []

    async def first_dependency() -> str:
        return "first"

    async def second_dependency() -> str:
        return "real-second"

    async def record(_request: Request, context: object) -> None:
        contexts.append(context)

    async def unused_resolver(_request: Request) -> None:
        return None

    app.add_dependency_request_guard(
        record, dependency=first_dependency, resolver=unused_resolver
    )
    app.add_dependency_request_guard(
        record, dependency=second_dependency, resolver=unused_resolver
    )
    app.dependency_overrides[second_dependency] = lambda: "overridden-second"

    @app.get("/api")
    async def api_route() -> dict[str, bool]:
        return {"ok": True}

    assert TestClient(app).get("/api").status_code == 200
    assert contexts == ["first", "overridden-second"]
```

- [ ] **Step 2: Prove RED**

Run: `uv run pytest packages/calango-core/tests/test_guards.py -q -k "registration_order or earlier_guard or resolves_once or later_guard_dependency"`
Expected: FAIL with `RuntimeError: A dependency request guard is already registered`.

- [ ] **Step 3: Implement ordered registrations in `guards.py`**

Replace the single-registration helpers with tuple-based ones and add the composite builder:

```python
import inspect

def compose_guard_dependencies(
    dependencies: tuple[RequestGuardDependency, ...],
) -> RequestGuardDependency:
    """Build one FastAPI dependency resolving every registered guard dependency.

    Each registration becomes a ``Depends(...)`` parameter, so FastAPI caches
    shared sub-dependencies and applies public ``dependency_overrides`` per
    registered dependency.
    """
    names = tuple(f"guard_context_{index}" for index in range(len(dependencies)))

    async def resolved_contexts(**contexts: Any) -> tuple[Any, ...]:
        return tuple(contexts[name] for name in names)

    resolved_contexts.__signature__ = inspect.Signature(  # ty: ignore[unresolved-attribute]
        [
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=Depends(dependency))
            for name, dependency in zip(names, dependencies, strict=True)
        ]
    )
    return resolved_contexts


async def run_dependency_request_guards(
    request: Request,
    owner: Any,
    contexts: tuple[Any, ...],
) -> None:
    """Run every dependency-aware guard once, in registration order."""
    registrations = owner._dependency_request_guards
    if not registrations:
        return

    guarded_owners = request.scope.setdefault(_DEPENDENCY_GUARDED_OWNERS_SCOPE_KEY, set())
    owner_id = id(owner)
    if owner_id in guarded_owners:
        return

    guarded_owners.add(owner_id)
    for registration, context in zip(registrations, contexts, strict=True):
        await registration.guard(request, context)


async def run_external_request_guards(request: Request, owner: Any) -> None:
    """Resolve and run guards for Starlette routes and mounted applications.

    Each resolver runs right before its guard, so a later resolver can use state
    an earlier guard stored on the request (e.g. the authenticated user).
    """
    await run_request_guards(request, owner)
    registrations = owner._dependency_request_guards
    if not registrations:
        return

    guarded_owners = request.scope.setdefault(_DEPENDENCY_GUARDED_OWNERS_SCOPE_KEY, set())
    owner_id = id(owner)
    if owner_id in guarded_owners:
        return

    guarded_owners.add(owner_id)
    for registration in registrations:
        context = await registration.resolver(request)
        await registration.guard(request, context)


def has_external_request_guards(owner: Any) -> bool:
    return has_simple_request_guards(owner) or bool(owner._dependency_request_guards)
```

Delete `run_dependency_request_guard` (singular). In `request_guard_dependency_boundary`, replace the dependency-guard branch with:

```python
        await run_request_guards(connection, owner)
        if owner._dependency_request_guards:
            if context is _UNRESOLVED_CONTEXT:
                raise RuntimeError("Dependency request guard context was not resolved")
            await run_dependency_request_guards(connection, owner, context)
```

In `RequestGuardDependencyOverrides.get`, return the composite directly — public overrides now apply to each registered dependency inside it:

```python
        if key is self.context_dependency:
            if not _HTTP_REQUEST_SCOPE.get() or self._context_override is None:
                return default
            return self._context_override
        return super().get(key, default)
```

- [ ] **Step 4: Append registrations in `app.py`**

```python
        self._dependency_request_guards: tuple[DependencyRequestGuardRegistration, ...] = ()
```

replaces `self._dependency_request_guard = None`, and `add_dependency_request_guard` becomes:

```python
        if self._startup_started:
            raise RuntimeError(
                "Dependency request guards cannot be registered after startup begins"
            )
        registration = DependencyRequestGuardRegistration(
            guard=guard,
            dependency=dependency,
            resolver=resolver,
        )
        self._dependency_request_guards = (*self._dependency_request_guards, registration)
        self._request_guard_dependency_overrides.set_context_override(
            compose_guard_dependencies(
                tuple(item.dependency for item in self._dependency_request_guards)
            )
        )
```

Update its docstring: "Guards run in registration order; each guard receives the context its own dependency (API routes) or resolver (Starlette routes and mounts) produced." Import `compose_guard_dependencies` from `calango.core.guards`.

In `test_guards.py`, the two tests that build `RequestGuardMiddleware` with a hand-made owner use `{"_request_guards": (guard,), "_dependency_request_guard": None}`; change the key to `"_dependency_request_guards": ()`.

- [ ] **Step 5: Prove GREEN across core and Identity**

Run: `uv run pytest packages/calango-core packages/calango-plugins/calango-identity -q`
Expected: PASS (Identity still registers exactly one guard; its override tests prove per-dependency overrides still work).

- [ ] **Step 6: Commit**

```bash
git add packages/calango-core
git commit -m "feat(core): compose dependency request guards in registration order"
```

### Task 2: Multitenancy package skeleton

**Files:**
- Create: `packages/calango-plugins/calango-multitenancy/pyproject.toml`
- Create: `packages/calango-plugins/calango-multitenancy/README.md`
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/__init__.py`
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/settings.py`
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/plugin.py`
- Create: `packages/calango-plugins/calango-multitenancy/tests/__init__.py`
- Create: `packages/calango-plugins/calango-multitenancy/tests/conftest.py`
- Create: `packages/calango-plugins/calango-multitenancy/tests/test_plugin.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/dependencies.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/__init__.py`
- Modify: `pyproject.toml` (workspace member, testpaths), `uv.lock`

- [ ] **Step 1: Create the package metadata**

`packages/calango-plugins/calango-multitenancy/pyproject.toml`:

```toml
[project]
name = "calango-multitenancy"
version = "0.1.0-dev"
description = "Calango Framework — Multitenancy plugin (PostgreSQL row-level security)"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "calango-core",
    "calango-plugin-base",
    "calango-identity",
    "fastapi>=0.141.1",
    "pydantic-settings>=2.14.2",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
]

[project.entry-points."calango.plugins"]
multitenancy = "calango_multitenancy.plugin:MultitenancyPlugin"

[tool.uv.sources]
calango-core = { workspace = true }
calango-plugin-base = { workspace = true }
calango-identity = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["calango_multitenancy"]
```

The build block matches `calango-identity`'s (hatchling, explicit wheel package). `README.md` starts as:

```markdown
# calango-multitenancy

PostgreSQL row-level-security multitenancy for Calango applications. Requires
`calango-identity`.
```

Add `"packages/calango-plugins/calango-multitenancy"` to `[tool.uv.workspace].members` and `"packages/calango-plugins/calango-multitenancy/tests"` to `[tool.pytest.ini_options].testpaths` in the root `pyproject.toml`, then run `uv lock && uv sync --all-packages`.

- [ ] **Step 2: Write the failing tests**

`tests/conftest.py` — keys are generated once per session; several workspace
packages own a `tests` package, so test modules never import `tests.conftest`
and share values through fixtures only:

```python
from __future__ import annotations

import pytest
from calango_identity import IdentityPlugin, IdentitySettings
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from calango import Calango
from calango.config import CalangoSettings, SecuritySettings


@pytest.fixture(scope="session")
def signing_keys() -> tuple[str, str]:
    """An ephemeral RS256 key pair (private PEM, public PEM) for the test session."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public


@pytest.fixture
def identity_settings(signing_keys: tuple[str, str]) -> IdentitySettings:
    private, public = signing_keys
    return IdentitySettings(PRIVATE_KEY=private, PUBLIC_KEY=public, REDIS_URL="memory://")


@pytest.fixture
def identity_plugin(identity_settings: IdentitySettings) -> IdentityPlugin:
    return IdentityPlugin(settings=identity_settings, refresh_store=InMemoryRefreshTokenStore())


@pytest.fixture
def app() -> Calango:
    return Calango(settings=CalangoSettings(security=SecuritySettings(SECRET_KEY="test-secret")))
```

`tests/test_plugin.py`:

```python
from __future__ import annotations

from importlib.metadata import entry_points

import pytest
from calango_multitenancy import MultitenancyPlugin, MultitenancySettings
from calango_plugin_base import PluginBase
from fastapi import FastAPI


def test_plugin_implements_plugin_base():
    assert isinstance(MultitenancyPlugin(), PluginBase)
    assert MultitenancyPlugin.name == "multitenancy"


def test_plugin_entry_point_is_installed():
    (entry_point,) = (
        item for item in entry_points(group="calango.plugins") if item.name == "multitenancy"
    )
    assert entry_point.load() is MultitenancyPlugin


def test_plugin_settings_class():
    assert MultitenancyPlugin().settings() is MultitenancySettings
    assert MultitenancySettings().TENANT_HEADER == "X-Tenant-ID"


def test_register_requires_a_calango_application():
    with pytest.raises(TypeError, match="Calango"):
        MultitenancyPlugin().register(FastAPI())


def test_register_requires_identity_first(app):
    with pytest.raises(RuntimeError, match="IdentityPlugin"):
        app.include_plugin(MultitenancyPlugin())


def test_register_after_identity_succeeds(app, identity_plugin):
    app.include_plugin(identity_plugin)
    app.include_plugin(MultitenancyPlugin())
```

- [ ] **Step 3: Prove RED**

Run: `uv run pytest packages/calango-plugins/calango-multitenancy/tests -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'calango_multitenancy'`.

- [ ] **Step 4: Add `identity_is_installed` to Identity**

In `calango_identity/dependencies.py`:

```python
def identity_is_installed(app: FastAPI) -> bool:
    """Return whether IdentityPlugin has been registered on ``app``."""
    return getattr(app.state, _USER_RESOLVER_STATE, None) is not None
```

Export it from `calango_identity/__init__.py` (`__all__` too).

- [ ] **Step 5: Implement the skeleton**

`calango_multitenancy/settings.py`:

```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class MultitenancySettings(BaseSettings):
    """Multitenancy settings, read from MULTITENANCY__* variables or .env."""

    TENANT_HEADER: str = "X-Tenant-ID"

    model_config = SettingsConfigDict(
        env_prefix="MULTITENANCY__",
        env_file=".env",
        extra="ignore",
    )
```

`calango_multitenancy/plugin.py`:

```python
from __future__ import annotations

from typing import ClassVar

from calango_identity import identity_is_installed
from calango_plugin_base import PluginMigration
from fastapi import FastAPI
from pydantic_settings import BaseSettings

from calango import Calango
from calango_multitenancy.settings import MultitenancySettings


class MultitenancyPlugin:
    """PostgreSQL row-level-security multitenancy. Register after IdentityPlugin."""

    name = "multitenancy"
    version = "0.1.0"
    requires: ClassVar[list[str]] = ["calango-identity>=0.1.0"]

    def __init__(self, settings: MultitenancySettings | None = None) -> None:
        self._settings = settings or MultitenancySettings()

    def register(self, app: FastAPI) -> None:
        if not isinstance(app, Calango):
            raise TypeError("MultitenancyPlugin requires a Calango application")
        if not identity_is_installed(app):
            raise RuntimeError("Register IdentityPlugin before MultitenancyPlugin")

    def import_models(self) -> None:
        return None

    def migrations(self) -> tuple[PluginMigration, ...]:
        return ()

    def settings(self) -> type[BaseSettings]:
        return MultitenancySettings

    def test_fixtures(self) -> list:
        return []

    def context_md(self) -> str:
        return """<!-- BLOCK: multitenancy -->
## Plugin: Multitenancy

PostgreSQL row-level security isolates tenant data inside the database.
<!-- END BLOCK: multitenancy -->"""
```

`calango_multitenancy/__init__.py`:

```python
from __future__ import annotations

from calango_multitenancy.plugin import MultitenancyPlugin
from calango_multitenancy.settings import MultitenancySettings

__all__ = ["MultitenancyPlugin", "MultitenancySettings"]
```

- [ ] **Step 6: Prove GREEN, run all gates, commit**

Run: `uv run pytest packages/calango-plugins/calango-multitenancy/tests -q` → PASS; then the four global gates.

```bash
git add pyproject.toml uv.lock packages/calango-plugins/calango-multitenancy packages/calango-plugins/calango-identity
git commit -m "feat(multitenancy): add plugin package skeleton"
```

### Task 3: Tenant and membership tables

**Files:**
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/models.py`
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/migrations/__init__.py`
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/migrations/versions/0001_multitenancy.py`
- Modify: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/plugin.py`
- Modify: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/__init__.py`
- Create: `packages/calango-plugins/calango-multitenancy/tests/test_models.py`
- Create: `packages/calango-plugins/calango-multitenancy/tests/integration/test_postgres_migrations.py`

- [ ] **Step 1: Write the failing model and descriptor tests**

`tests/test_models.py`:

```python
from __future__ import annotations

from calango_multitenancy import MultitenancyPlugin, Tenant, TenantMembership
from sqlalchemy import CheckConstraint, UniqueConstraint


def test_tenant_table_has_unique_slug_and_name():
    table = Tenant.__table__
    assert table.name == "tenants"
    assert table.c.slug.unique is True
    assert table.c.slug.type.length == 63
    assert table.c.name.nullable is False


def test_membership_links_tenant_and_identity_user_once():
    table = TenantMembership.__table__
    assert table.name == "tenant_memberships"
    assert {fk.target_fullname for fk in table.foreign_keys} == {
        "tenants.id",
        "identity_users.id",
    }
    unique = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("tenant_id", "user_id") in unique
    checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
    assert any("owner" in str(check.sqltext) for check in checks)


def test_plugin_contributes_its_migration_after_identity():
    (descriptor,) = MultitenancyPlugin().migrations()
    assert descriptor.name == "multitenancy"
    assert descriptor.depends_on == ("identity",)
    assert descriptor.versions.joinpath("0001_multitenancy.py").is_file()
```

Give the multitenancy tests their own minimal Alembic environment (the same
45-line `env.py` Identity's tests use):

```bash
mkdir -p packages/calango-plugins/calango-multitenancy/tests/alembic
cp packages/calango-plugins/calango-identity/tests/alembic/env.py \
   packages/calango-plugins/calango-multitenancy/tests/alembic/env.py
```

`tests/integration/test_postgres_migrations.py` (uses the root `postgres_url`
fixture and the `identity_plugin` fixture from Task 2):

```python
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from calango_multitenancy import MultitenancyPlugin
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from calango_cli.migrations import MigrationResources, version_locations

pytestmark = pytest.mark.integration
SCRIPT_LOCATION = Path(__file__).parents[1] / "alembic"


def _run_alembic(url: str, command_name: str, revision: str, locations: tuple[Path, ...]) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    config.set_main_option("version_locations", os.pathsep.join(map(str, locations)))
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", url)
    getattr(command, command_name)(config, revision)


async def _tables(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
    finally:
        await engine.dispose()


async def test_multitenancy_tables_upgrade_after_identity_and_downgrade(
    postgres_url, identity_plugin
):
    with MigrationResources() as resources:
        locations = version_locations(
            (*identity_plugin.migrations(), *MultitenancyPlugin().migrations()),
            resources=resources,
        )
        await asyncio.to_thread(_run_alembic, postgres_url, "upgrade", "heads", locations)
        assert {"tenants", "tenant_memberships", "identity_users"} <= await _tables(postgres_url)

        await asyncio.to_thread(_run_alembic, postgres_url, "downgrade", "base", locations)
        assert not ({"tenants", "tenant_memberships"} & await _tables(postgres_url))
```

- [ ] **Step 2: Prove RED**

Run: `uv run pytest packages/calango-plugins/calango-multitenancy/tests -q`
Expected: FAIL with `ImportError: cannot import name 'Tenant'`.

- [ ] **Step 3: Implement the models**

`calango_multitenancy/models.py`:

```python
from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from calango.db import Base

TENANT_ROLES = ("owner", "member")


class Tenant(Base):
    """A tenant. Global table: queried before any tenant context exists."""

    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class TenantMembership(Base):
    """A user's role in a tenant. Global table, like ``tenants``."""

    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
        CheckConstraint("role IN ('owner', 'member')", name="ck_tenant_memberships_role"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity_users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
```

Import `calango_identity.models` at the top of `models.py` (`import calango_identity.models  # noqa: F401 — registers identity_users for the foreign key`) so the foreign-key target is always in `Base.metadata`.

- [ ] **Step 4: Write the revision**

`calango_multitenancy/migrations/__init__.py` is empty. `migrations/versions/0001_multitenancy.py` follows `calango_identity/migrations/versions/0001_identity.py`:

```python
"""Create the tenant and tenant-membership tables.

Revision ID: multitenancy_0001
Revises: None
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "multitenancy_0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _audit_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "tenant_memberships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_audit_columns(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["identity_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_tenant_memberships_role"),
    )
    op.create_index(
        "ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"]
    )
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_table("tenants")
```

- [ ] **Step 5: Wire the contract methods and exports**

In `plugin.py`:

```python
    def import_models(self) -> None:
        """Register the tenant models with canonical metadata."""
        import_module("calango_multitenancy.models")

    def migrations(self) -> tuple[PluginMigration, ...]:
        """Tenant tables reference identity_users, so they run after Identity."""
        versions = files("calango_multitenancy.migrations.versions")
        return (PluginMigration("multitenancy", versions, ("identity",)),)
```

(with `from importlib import import_module` and `from importlib.resources import files`). Export `Tenant` and `TenantMembership` from `__init__.py`.

- [ ] **Step 6: Prove GREEN, run all gates, commit**

Run: `uv run pytest packages/calango-plugins/calango-multitenancy -q` → PASS (the integration test runs when Docker or `CALANGO_TEST_POSTGRES_URL` is available).

```bash
git add packages/calango-plugins/calango-multitenancy
git commit -m "feat(multitenancy): add tenant and membership tables"
```
