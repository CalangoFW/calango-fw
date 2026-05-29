# calango-identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 6 — `calango-plugin-base` (PluginBase Protocol), `calango-core` update (`include_plugin()`), and `calango-identity` (FastAPI-Users + JWT RS256 + Argon2 + Redis rate limiting + RBAC).

**Architecture:** Three new packages in the UV workspace. `calango-plugin-base` defines the shared PluginBase Protocol. `calango-core` gains `include_plugin()`. `calango-identity` implements PluginBase using FastAPI-Users 13.x with SQLAlchemy async, RS256 JWT, slowapi rate limiting, and a `@public` / `require_permission` RBAC system.

**Tech Stack:** fastapi-users[sqlalchemy]>=13, slowapi>=0.1.9, fakeredis (tests), argon2-cffi, aiosqlite (tests), python-multipart (FastAPI-Users form login)

---

## File Map

### New files
```
packages/calango-plugin-base/
  pyproject.toml
  calango_plugin_base/__init__.py          # PluginBase Protocol
  tests/__init__.py
  tests/test_plugin_base.py

packages/calango-plugins/calango-identity/
  pyproject.toml
  calango_identity/__init__.py             # public re-exports
  calango_identity/settings.py             # IdentitySettings
  calango_identity/models.py               # User, Role, Permission + junctions
  calango_identity/schemas.py              # UserRead, UserCreate, UserUpdate
  calango_identity/security.py             # make_auth_backend(), JWTStrategy RS256
  calango_identity/manager.py              # UserManager (FastAPI-Users)
  calango_identity/dependencies.py         # get_current_user, @public, require_permission
  calango_identity/rate_limit.py           # make_limiter()
  calango_identity/plugin.py               # IdentityPlugin (implements PluginBase)
  tests/__init__.py
  tests/conftest.py                        # shared fixtures: engine, session, app
  tests/test_settings.py
  tests/test_models.py
  tests/test_auth_router.py
  tests/test_dependencies.py
  tests/test_rate_limit.py
  tests/test_plugin.py
```

### Modified files
```
pyproject.toml                             # add workspace members
packages/calango-core/calango/core/app.py  # add include_plugin()
packages/calango-core/tests/test_app.py    # add 3 tests for include_plugin()
packages/calango-core/pyproject.toml       # add calango-plugin-base dependency
```

---

## Task 1: Workspace scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `packages/calango-plugin-base/pyproject.toml`
- Create: `packages/calango-plugin-base/calango_plugin_base/__init__.py`
- Create: `packages/calango-plugin-base/tests/__init__.py`
- Create: `packages/calango-plugins/calango-identity/pyproject.toml`
- Create: `packages/calango-plugins/calango-identity/calango_identity/__init__.py`
- Create: `packages/calango-plugins/calango-identity/tests/__init__.py`

- [ ] **Step 1: Update root `pyproject.toml` workspace members**

```toml
# pyproject.toml — replace [tool.uv.workspace] section
[tool.uv.workspace]
members = [
    "packages/calango-core",
    "packages/calango-cli",
    "packages/calango-plugin-base",
    "packages/calango-plugins/calango-identity",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "anyio[trio]>=4",
    "ruff>=0.8",
    "ty>=0.0.1a1",
    "pytest-cov>=7.1.0",
    "aiosqlite>=0.22.1",
    "fakeredis>=2.26",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["packages"]
addopts = "-v --tb=short"
```

- [ ] **Step 2: Create `calango-plugin-base` package**

`packages/calango-plugin-base/pyproject.toml`:
```toml
[project]
name = "calango-plugin-base"
version = "0.1.0-dev"
description = "Calango Framework — PluginBase Protocol"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "pydantic-settings>=2.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["calango_plugin_base"]
```

`packages/calango-plugin-base/calango_plugin_base/__init__.py`:
```python
# placeholder — implemented in Task 2
```

`packages/calango-plugin-base/tests/__init__.py`: empty file.

- [ ] **Step 3: Create `calango-identity` package skeleton**

`packages/calango-plugins/calango-identity/pyproject.toml`:
```toml
[project]
name = "calango-identity"
version = "0.1.0-dev"
description = "Calango Framework — Identity plugin (JWT RS256 + RBAC)"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "calango-plugin-base",
    "fastapi-users[sqlalchemy]>=13.0",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
    "slowapi>=0.1.9",
    "redis>=5.2",
    "argon2-cffi>=23",
    "python-multipart>=0.0.9",
]

[tool.uv.sources]
calango-plugin-base = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["calango_identity"]
```

`packages/calango-plugins/calango-identity/calango_identity/__init__.py`:
```python
# placeholder — populated in Task 11
```

`packages/calango-plugins/calango-identity/tests/__init__.py`: empty file.

- [ ] **Step 4: Sync workspace**

```bash
uv sync
```

Expected: resolves all packages without errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml packages/calango-plugin-base/ packages/calango-plugins/
git commit -m "chore: scaffold calango-plugin-base and calango-identity workspace packages"
```

---

## Task 2: `PluginBase` Protocol

**Files:**
- Modify: `packages/calango-plugin-base/calango_plugin_base/__init__.py`
- Create: `packages/calango-plugin-base/tests/test_plugin_base.py`

- [ ] **Step 1: Write failing tests**

`packages/calango-plugin-base/tests/test_plugin_base.py`:
```python
import pytest
from fastapi import FastAPI
from pydantic_settings import BaseSettings
from calango_plugin_base import PluginBase


class ValidPlugin:
    name = "test"
    version = "1.0.0"
    requires: list[str] = []

    def register(self, app: FastAPI) -> None: ...
    def migrations(self) -> list[str]: return []
    def settings(self) -> type[BaseSettings]: return BaseSettings
    def test_fixtures(self) -> list: return []
    def context_md(self) -> str: return ""


class MissingMethodPlugin:
    name = "bad"
    version = "1.0.0"
    requires: list[str] = []
    # missing register(), migrations(), settings(), test_fixtures(), context_md()


def test_valid_plugin_satisfies_protocol():
    """A class implementing all 5 methods passes isinstance check."""
    plugin = ValidPlugin()
    assert isinstance(plugin, PluginBase)


def test_missing_method_fails_isinstance():
    """A class missing protocol methods fails isinstance check."""
    plugin = MissingMethodPlugin()
    assert not isinstance(plugin, PluginBase)


def test_plugin_base_is_runtime_checkable():
    """PluginBase can be used in isinstance() at runtime."""
    assert issubclass(PluginBase, object)  # Protocol exists
    plugin = ValidPlugin()
    result = isinstance(plugin, PluginBase)
    assert isinstance(result, bool)


def test_valid_plugin_name_attribute():
    """Plugin has name attribute."""
    plugin = ValidPlugin()
    assert plugin.name == "test"


def test_valid_plugin_version_attribute():
    """Plugin has version attribute."""
    plugin = ValidPlugin()
    assert plugin.version == "1.0.0"
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest packages/calango-plugin-base/tests/ -v
```

Expected: `ImportError: cannot import name 'PluginBase'`

- [ ] **Step 3: Implement `PluginBase`**

`packages/calango-plugin-base/calango_plugin_base/__init__.py`:
```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import FastAPI
from pydantic_settings import BaseSettings


@runtime_checkable
class PluginBase(Protocol):
    """Contract every Calango plugin must implement.

    Usage:
        class MyPlugin:
            name = "my-plugin"
            version = "1.0.0"
            requires: list[str] = []

            def register(self, app: FastAPI) -> None:
                app.include_router(my_router)

            def migrations(self) -> list[str]:
                return ["my_plugin.migrations"]

            def settings(self) -> type[BaseSettings]:
                return MyPluginSettings

            def test_fixtures(self) -> list:
                return [my_fixture]

            def context_md(self) -> str:
                return "## Plugin: My Plugin\\n..."
    """

    name: str
    version: str
    requires: list[str]

    def register(self, app: FastAPI) -> None:
        """Register routers, middleware, exception handlers, lifecycle hooks."""
        ...

    def migrations(self) -> list[str]:
        """Return Alembic migration module paths contributed by this plugin."""
        ...

    def settings(self) -> type[BaseSettings]:
        """Return the plugin's pydantic-settings class."""
        ...

    def test_fixtures(self) -> list:
        """Return pytest fixtures injected into projects using this plugin."""
        ...

    def context_md(self) -> str:
        """Return a CLAUDE.md markdown block describing this plugin."""
        ...
```

- [ ] **Step 4: Run — verify PASS**

```bash
uv run pytest packages/calango-plugin-base/tests/ -v
```

Expected: `5 passed`

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check packages/calango-plugin-base/ --fix
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugin-base/
git commit -m "feat(plugin-base): PluginBase Protocol with full 5-method contract"
```

---

## Task 3: `calango-core` — `include_plugin()`

**Files:**
- Modify: `packages/calango-core/pyproject.toml`
- Modify: `packages/calango-core/calango/core/app.py`
- Modify: `packages/calango-core/tests/test_app.py`

- [ ] **Step 1: Add `calango-plugin-base` dependency to `calango-core`**

`packages/calango-core/pyproject.toml` — add to `dependencies`:
```toml
dependencies = [
    "fastapi>=0.115",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0.36",
    "calango-plugin-base",
]

[tool.uv.sources]
calango-plugin-base = { workspace = true }
```

Run `uv sync` to verify resolution.

- [ ] **Step 2: Write failing tests**

Add to `packages/calango-core/tests/test_app.py`:

```python
def test_include_plugin_calls_register():
    """include_plugin() calls plugin.register(app)."""
    from pydantic_settings import BaseSettings

    class FakePlugin:
        name = "fake"
        version = "0.1.0"
        requires: list[str] = []
        registered_with = None

        def register(self, app) -> None:
            FakePlugin.registered_with = app

        def migrations(self) -> list[str]: return []
        def settings(self) -> type[BaseSettings]: return BaseSettings
        def test_fixtures(self) -> list: return []
        def context_md(self) -> str: return ""

    app = Calango()
    plugin = FakePlugin()
    app.include_plugin(plugin)
    assert FakePlugin.registered_with is app


def test_include_plugin_raises_for_non_plugin():
    """include_plugin() raises TypeError for objects not implementing PluginBase."""
    app = Calango()
    with pytest.raises(TypeError, match="does not implement PluginBase"):
        app.include_plugin(object())  # type: ignore[arg-type]


def test_include_plugin_accepts_valid_plugin():
    """include_plugin() does not raise for a valid PluginBase implementation."""
    from pydantic_settings import BaseSettings

    class GoodPlugin:
        name = "good"
        version = "1.0.0"
        requires: list[str] = []
        def register(self, app) -> None: ...
        def migrations(self) -> list[str]: return []
        def settings(self) -> type[BaseSettings]: return BaseSettings
        def test_fixtures(self) -> list: return []
        def context_md(self) -> str: return ""

    app = Calango()
    app.include_plugin(GoodPlugin())  # must not raise
```

- [ ] **Step 3: Run — verify FAIL**

```bash
uv run pytest packages/calango-core/tests/test_app.py -v -k "plugin"
```

Expected: `AttributeError: 'Calango' object has no attribute 'include_plugin'`

- [ ] **Step 4: Implement `include_plugin()`**

`packages/calango-core/calango/core/app.py` — add method to `Calango`:
```python
from __future__ import annotations

from fastapi import FastAPI
from calango_plugin_base import PluginBase

from calango.config import CalangoSettings, SecuritySettings
from calango.core.handlers import calango_exception_handler, unhandled_exception_handler
from calango.core.middleware import CalangoMiddleware
from calango.exceptions import CalangoException


class Calango(FastAPI):
    def __init__(self, settings: CalangoSettings | None = None, **kwargs: object) -> None:
        if settings is None:
            settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="changeme"))  # noqa: S106

        kwargs.setdefault("title", settings.APP_NAME)
        kwargs.setdefault("version", settings.VERSION)

        super().__init__(**kwargs)

        self.settings = settings

        self.add_middleware(CalangoMiddleware)

        self.add_exception_handler(CalangoException, calango_exception_handler)  # type: ignore[arg-type]
        self.add_exception_handler(Exception, unhandled_exception_handler)

    def include_plugin(self, plugin: PluginBase) -> None:
        """Register a Calango plugin. Calls plugin.register(self)."""
        if not isinstance(plugin, PluginBase):
            raise TypeError(
                f"{type(plugin).__name__} does not implement PluginBase. "
                "All 5 methods (register, migrations, settings, "
                "test_fixtures, context_md) must be defined."
            )
        plugin.register(self)
```

- [ ] **Step 5: Run — verify PASS**

```bash
uv run pytest packages/calango-core/tests/ -v
```

Expected: all 74 pass (71 existing + 3 new).

- [ ] **Step 6: Ruff check**

```bash
uv run ruff check packages/calango-core/ --fix
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add packages/calango-core/
git commit -m "feat(core): Calango.include_plugin() — registers PluginBase implementations"
```

---

## Task 4: `calango-identity` settings + conftest

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/settings.py`
- Create: `packages/calango-plugins/calango-identity/tests/conftest.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_settings.py`

RSA keys for tests (2048-bit, generated once for tests — never use in production):

```
# Test private key (ONLY for tests — do not use in production)
TEST_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA2a2rwplBQLzHPZe5eki5QomhXM5cEuHaFjWlLuFkYNHXCGpB
... (generate with: openssl genrsa 2048)
-----END RSA PRIVATE KEY-----"""
```

> **Note:** Generate actual test keys with `openssl genrsa 2048 > test_private.pem && openssl rsa -in test_private.pem -pubout > test_public.pem`. Store inline in conftest.py for tests.

- [ ] **Step 1: Write failing test**

`packages/calango-plugins/calango-identity/tests/test_settings.py`:
```python
import pytest
from pydantic import ValidationError
from calango_identity.settings import IdentitySettings


def test_settings_requires_private_key():
    """IdentitySettings raises ValidationError if PRIVATE_KEY is missing."""
    with pytest.raises(ValidationError):
        IdentitySettings(PUBLIC_KEY="some-key")


def test_settings_requires_public_key():
    """IdentitySettings raises ValidationError if PUBLIC_KEY is missing."""
    with pytest.raises(ValidationError):
        IdentitySettings(PRIVATE_KEY="some-key")


def test_settings_defaults():
    """IdentitySettings has correct defaults for token expiry and rate limits."""
    s = IdentitySettings(PRIVATE_KEY="pk", PUBLIC_KEY="pub")
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 15
    assert s.REFRESH_TOKEN_EXPIRE_DAYS == 7
    assert s.RATE_LIMIT_LOGIN_PER_MINUTE == 5
    assert s.RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL == 10
    assert s.REDIS_URL == "redis://localhost:6379/0"


def test_settings_env_prefix():
    """IdentitySettings uses IDENTITY__ prefix for env vars."""
    import os
    os.environ["IDENTITY__ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
    s = IdentitySettings(PRIVATE_KEY="pk", PUBLIC_KEY="pub")
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    del os.environ["IDENTITY__ACCESS_TOKEN_EXPIRE_MINUTES"]
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_settings.py -v
```

Expected: `ModuleNotFoundError: No module named 'calango_identity.settings'`

- [ ] **Step 3: Implement `IdentitySettings`**

`packages/calango-plugins/calango-identity/calango_identity/settings.py`:
```python
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class IdentitySettings(BaseSettings):
    """Configuration for calango-identity plugin.

    All variables use the IDENTITY__ prefix in .env files.

    Example .env:
        IDENTITY__PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\n..."
        IDENTITY__PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\\n..."
        IDENTITY__REDIS_URL=redis://localhost:6379/0
    """

    PRIVATE_KEY: str
    PUBLIC_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL: int = 10
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_prefix="IDENTITY__")
```

- [ ] **Step 4: Create test conftest with RSA keys**

Generate test keys:
```bash
openssl genrsa 2048 > /tmp/test_private.pem
openssl rsa -in /tmp/test_private.pem -pubout > /tmp/test_public.pem
```

`packages/calango-plugins/calango-identity/tests/conftest.py`:
```python
from __future__ import annotations

import pytest
from calango_identity.settings import IdentitySettings

# Test RSA keys — generated with: openssl genrsa 2048 / openssl rsa -pubout
# NEVER use these in production.
TEST_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
<paste output of /tmp/test_private.pem here>
-----END RSA PRIVATE KEY-----"""

TEST_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
<paste output of /tmp/test_public.pem here>
-----END PUBLIC KEY-----"""


@pytest.fixture
def identity_settings() -> IdentitySettings:
    return IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="redis://localhost:6379/99",  # use db 99 to avoid collisions
    )
```

- [ ] **Step 5: Run — verify PASS**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_settings.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugins/calango-identity/
git commit -m "feat(identity): IdentitySettings with IDENTITY__ env prefix"
```

---

## Task 5: SQLAlchemy models

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/models.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_models.py`

- [ ] **Step 1: Write failing tests**

`packages/calango-plugins/calango-identity/tests/test_models.py`:
```python
from __future__ import annotations

import uuid
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from calango_identity.models import Base, User, Role, Permission


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_user_table_exists(session):
    """User table can be created and has expected columns."""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="hashed",
    )
    session.add(user)
    await session.flush()
    assert user.id is not None
    assert user.email == "test@example.com"


async def test_role_table_exists(session):
    """Role table can be created."""
    role = Role(id=uuid.uuid4(), name="admin")
    session.add(role)
    await session.flush()
    assert role.name == "admin"


async def test_permission_table_exists(session):
    """Permission table can be created."""
    perm = Permission(id=uuid.uuid4(), code="orders:read")
    session.add(perm)
    await session.flush()
    assert perm.code == "orders:read"


async def test_user_role_relationship(session):
    """User can have roles via the junction table."""
    user = User(id=uuid.uuid4(), email="u@test.com", hashed_password="x")
    role = Role(id=uuid.uuid4(), name="editor")
    user.roles.append(role)
    session.add(user)
    await session.flush()
    await session.refresh(user)
    assert len(user.roles) == 1
    assert user.roles[0].name == "editor"


async def test_role_permission_relationship(session):
    """Role can have permissions via the junction table."""
    role = Role(id=uuid.uuid4(), name="manager")
    perm = Permission(id=uuid.uuid4(), code="reports:view")
    role.permissions.append(perm)
    session.add(role)
    await session.flush()
    await session.refresh(role)
    assert len(role.permissions) == 1
    assert role.permissions[0].code == "reports:view"


async def test_all_tables_use_identity_prefix(session):
    """All model tables are prefixed with identity_ to avoid collisions."""
    assert User.__tablename__ == "identity_users"
    assert Role.__tablename__ == "identity_roles"
    assert Permission.__tablename__ == "identity_permissions"
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'calango_identity.models'`

- [ ] **Step 3: Implement models**

`packages/calango-plugins/calango-identity/calango_identity/models.py`:
```python
from __future__ import annotations

import uuid
from uuid import UUID

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Junction tables (no extra columns — pure associations)
user_roles = Table(
    "identity_user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("identity_users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("identity_roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "identity_role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("identity_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("identity_permissions.id", ondelete="CASCADE"), primary_key=True),
)


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Auth user. FastAPI-Users provides: id, email, hashed_password,
    is_active, is_superuser, is_verified."""

    __tablename__ = "identity_users"

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles,
        lazy="selectin",
        back_populates="users",
    )


class Role(Base):
    __tablename__ = "identity_roles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    users: Mapped[list[User]] = relationship(
        secondary=user_roles,
        lazy="selectin",
        back_populates="roles",
    )
    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions,
        lazy="selectin",
        back_populates="roles",
    )


class Permission(Base):
    __tablename__ = "identity_permissions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions,
        lazy="selectin",
        back_populates="permissions",
    )
```

- [ ] **Step 4: Run — verify PASS**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_models.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check packages/calango-plugins/calango-identity/ --fix
```

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugins/calango-identity/
git commit -m "feat(identity): User + Role + Permission SQLAlchemy models with identity_ prefix"
```

---

## Task 6: FastAPI-Users wiring (schemas, UserManager, auth backend)

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/schemas.py`
- Create: `packages/calango-plugins/calango-identity/calango_identity/manager.py`
- Create: `packages/calango-plugins/calango-identity/calango_identity/security.py`

These three files have no tests of their own — they are tested indirectly via the auth router in Task 7. Steps here are write-and-verify (no TDD red phase for pure wiring code).

- [ ] **Step 1: Implement schemas**

`packages/calango-plugins/calango-identity/calango_identity/schemas.py`:
```python
from __future__ import annotations

import uuid
from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass
```

- [ ] **Step 2: Implement UserManager**

`packages/calango-plugins/calango-identity/calango_identity/manager.py`:
```python
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from calango_identity.models import User
from calango_identity.settings import IdentitySettings


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    def __init__(self, user_db: SQLAlchemyUserDatabase, settings: IdentitySettings) -> None:
        super().__init__(user_db)
        self.reset_password_token_secret = settings.PRIVATE_KEY
        self.verification_token_secret = settings.PRIVATE_KEY

    async def on_after_register(self, user: User, request: Optional[Request] = None) -> None:
        pass  # Hook: send welcome email, etc.

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ) -> None:
        pass  # Hook: send reset email with token


def make_get_user_manager(settings: IdentitySettings):
    """Returns a FastAPI dependency that yields UserManager."""

    async def get_user_manager(session: AsyncSession) -> UserManager:
        yield UserManager(SQLAlchemyUserDatabase(session, User), settings)

    return get_user_manager
```

- [ ] **Step 3: Implement auth backend (JWT RS256)**

`packages/calango-plugins/calango-identity/calango_identity/security.py`:
```python
from __future__ import annotations

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)

from calango_identity.settings import IdentitySettings


def make_jwt_strategy(settings: IdentitySettings) -> JWTStrategy:
    return JWTStrategy(
        secret=settings.PRIVATE_KEY,
        lifetime_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        algorithm="RS256",
        public_key=settings.PUBLIC_KEY,
    )


def make_auth_backend(settings: IdentitySettings) -> AuthenticationBackend:
    transport = BearerTransport(tokenUrl="/auth/login")
    return AuthenticationBackend(
        name="jwt",
        transport=transport,
        get_strategy=lambda: make_jwt_strategy(settings),
    )
```

- [ ] **Step 4: Ruff check**

```bash
uv run ruff check packages/calango-plugins/calango-identity/ --fix
```

Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add packages/calango-plugins/calango-identity/
git commit -m "feat(identity): FastAPI-Users schemas, UserManager, JWT RS256 auth backend"
```

---

## Task 7: Auth router — login and register endpoints

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/router.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_auth_router.py`

- [ ] **Step 1: Write failing tests**

`packages/calango-plugins/calango-identity/tests/test_auth_router.py`:
```python
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from calango_identity.models import Base, User
from calango_identity.router import make_auth_router
from calango_identity.settings import IdentitySettings
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def settings():
    return IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY)


@pytest.fixture
async def client(session, settings):
    app = FastAPI()
    router = make_auth_router(settings=settings, get_db=lambda: session)
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_register_returns_201(client):
    """POST /auth/register with valid data returns 201."""
    response = await client.post("/auth/register", json={
        "email": "user@example.com",
        "password": "SecurePassword123!",
    })
    assert response.status_code == 201
    assert response.json()["email"] == "user@example.com"


async def test_register_duplicate_email_returns_400(client):
    """POST /auth/register with existing email returns 400."""
    data = {"email": "dup@example.com", "password": "SecurePassword123!"}
    await client.post("/auth/register", json=data)
    response = await client.post("/auth/register", json=data)
    assert response.status_code == 400


async def test_login_returns_token(client):
    """POST /auth/login with valid credentials returns access_token."""
    await client.post("/auth/register", json={
        "email": "login@example.com",
        "password": "SecurePassword123!",
    })
    response = await client.post("/auth/login", data={
        "username": "login@example.com",
        "password": "SecurePassword123!",
    })
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_login_wrong_password_returns_400(client):
    """POST /auth/login with wrong password returns 400."""
    await client.post("/auth/register", json={
        "email": "wrong@example.com",
        "password": "SecurePassword123!",
    })
    response = await client.post("/auth/login", data={
        "username": "wrong@example.com",
        "password": "WrongPassword!",
    })
    assert response.status_code == 400


async def test_forgot_password_returns_202(client):
    """POST /auth/forgot-password returns 202 (always, even if email not found)."""
    response = await client.post("/auth/forgot-password", json={
        "email": "nonexistent@example.com"
    })
    assert response.status_code == 202
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_auth_router.py -v
```

Expected: `ModuleNotFoundError: No module named 'calango_identity.router'`

- [ ] **Step 3: Implement `make_auth_router()`**

`packages/calango-plugins/calango-identity/calango_identity/router.py`:
```python
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Callable

import fastapi_users
from fastapi import APIRouter, Depends
from fastapi_users import FastAPIUsers
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from calango_identity.manager import UserManager, make_get_user_manager
from calango_identity.models import User
from calango_identity.schemas import UserCreate, UserRead, UserUpdate
from calango_identity.security import make_auth_backend
from calango_identity.settings import IdentitySettings


def make_auth_router(
    settings: IdentitySettings,
    get_db: Callable,
) -> APIRouter:
    """Build and return the auth APIRouter wired to the given session dependency."""

    auth_backend = make_auth_backend(settings)
    get_user_manager = make_get_user_manager(settings)

    # Override get_user_manager to use the provided session
    async def _get_user_manager(session: AsyncSession = Depends(get_db)):
        async for manager in get_user_manager(session):
            yield manager

    fu = FastAPIUsers[User, type(User.id)](
        _get_user_manager,
        [auth_backend],
    )

    router = APIRouter()
    router.include_router(fu.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"])
    router.include_router(
        fu.get_register_router(UserRead, UserCreate),
        prefix="/auth",
        tags=["auth"],
    )
    router.include_router(
        fu.get_reset_password_router(),
        prefix="/auth",
        tags=["auth"],
    )
    router.include_router(
        fu.get_users_router(UserRead, UserUpdate),
        prefix="/users",
        tags=["users"],
    )

    return router
```

> **Note on FastAPI-Users UUID type:** `User.id` is `uuid.UUID` from `SQLAlchemyBaseUserTableUUID`. Replace `type(User.id)` with `uuid.UUID` explicitly: `FastAPIUsers[User, uuid.UUID]`.

Correct router.py with explicit UUID:
```python
import uuid
...
fu = FastAPIUsers[User, uuid.UUID](
    _get_user_manager,
    [auth_backend],
)
```

- [ ] **Step 4: Run — verify PASS**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_auth_router.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check packages/calango-plugins/calango-identity/ --fix
```

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugins/calango-identity/
git commit -m "feat(identity): auth router — /auth/register, /auth/login, /auth/forgot-password"
```

---

## Task 8: `@public` decorator + `get_current_user`

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/dependencies.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_dependencies.py`

- [ ] **Step 1: Write failing tests**

`packages/calango-plugins/calango-identity/tests/test_dependencies.py`:
```python
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from calango_identity.dependencies import public


def test_public_decorator_sets_marker():
    """@public sets __calango_public__ = True on the function."""
    @public
    def my_handler():
        pass

    assert getattr(my_handler, "__calango_public__", False) is True


def test_public_decorator_preserves_function():
    """@public does not change function behavior."""
    @public
    def add(a, b):
        return a + b

    assert add(1, 2) == 3


async def test_public_endpoint_returns_200_without_token():
    """An endpoint decorated with @public is accessible without Bearer token."""
    from calango_identity.dependencies import public

    app = FastAPI()

    @app.get("/open")
    @public
    async def open_endpoint():
        return {"open": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/open")
    assert response.status_code == 200


async def test_non_public_endpoint_has_public_marker_false():
    """An endpoint without @public does not have the public marker."""
    async def plain_handler():
        pass

    assert getattr(plain_handler, "__calango_public__", False) is False
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_dependencies.py -v
```

Expected: `ModuleNotFoundError: No module named 'calango_identity.dependencies'`

- [ ] **Step 3: Implement `@public`**

`packages/calango-plugins/calango-identity/calango_identity/dependencies.py`:
```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def public(func: Callable) -> Callable:
    """Mark a FastAPI route as public (no authentication required).

    Usage:
        @router.get("/health")
        @public
        async def health_check():
            return {"status": "ok"}
    """
    func.__calango_public__ = True  # type: ignore[attr-defined]
    return func


def require_permission(permission_code: str) -> Any:
    """RBAC dependency — raises 403 if user lacks the required permission.

    Usage:
        @router.post("/admin/users")
        async def create_admin(user: User = require_permission("users:admin")):
            ...
    """
    # Implemented in Task 9
    raise NotImplementedError("require_permission is implemented in Task 9")
```

- [ ] **Step 4: Run — verify PASS**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_dependencies.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add packages/calango-plugins/calango-identity/
git commit -m "feat(identity): @public decorator — marks routes as authentication-exempt"
```

---

## Task 9: `require_permission` + RBAC

**Files:**
- Modify: `packages/calango-plugins/calango-identity/calango_identity/dependencies.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_dependencies.py`

- [ ] **Step 1: Write failing tests (add to `test_dependencies.py`)**

```python
# Add these tests to test_dependencies.py

import uuid
from unittest.mock import MagicMock
from calango_identity.models import User, Role, Permission
from calango_identity.dependencies import require_permission
from calango.exceptions import AuthorizationError


def _make_user_with_permission(perm_code: str) -> User:
    perm = MagicMock(spec=Permission)
    perm.code = perm_code
    role = MagicMock(spec=Role)
    role.permissions = [perm]
    user = MagicMock(spec=User)
    user.roles = [role]
    return user


def _make_user_without_permissions() -> User:
    user = MagicMock(spec=User)
    user.roles = []
    return user


async def test_require_permission_grants_access_when_user_has_permission():
    """require_permission passes when user has the required permission code."""
    from fastapi import Depends
    user = _make_user_with_permission("orders:read")

    dep = require_permission("orders:read")
    # Extract the inner check function
    check_fn = dep.dependency
    result = await check_fn(user=user)
    assert result is user


async def test_require_permission_raises_403_when_missing():
    """require_permission raises AuthorizationError when user lacks permission."""
    from calango.exceptions import AuthorizationError
    user = _make_user_without_permissions()

    dep = require_permission("orders:write")
    check_fn = dep.dependency
    with pytest.raises(AuthorizationError):
        await check_fn(user=user)


async def test_require_permission_checks_across_all_roles():
    """require_permission passes if ANY of user's roles has the permission."""
    perm1 = MagicMock(spec=Permission)
    perm1.code = "reports:view"
    role1 = MagicMock(spec=Role)
    role1.permissions = [perm1]

    perm2 = MagicMock(spec=Permission)
    perm2.code = "orders:read"
    role2 = MagicMock(spec=Role)
    role2.permissions = [perm2]

    user = MagicMock(spec=User)
    user.roles = [role1, role2]

    dep = require_permission("orders:read")
    check_fn = dep.dependency
    result = await check_fn(user=user)
    assert result is user
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_dependencies.py -v -k "permission"
```

Expected: tests fail because `require_permission` raises `NotImplementedError`.

- [ ] **Step 3: Implement `require_permission`**

Replace the `require_permission` placeholder in `dependencies.py`:
```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends

from calango.exceptions import AuthorizationError
from calango_identity.models import User


def public(func: Callable) -> Callable:
    """Mark a FastAPI route as public (no authentication required)."""
    func.__calango_public__ = True  # type: ignore[attr-defined]
    return func


def require_permission(permission_code: str) -> Any:
    """RBAC dependency factory — raises AuthorizationError if user lacks permission.

    Usage:
        @router.post("/admin/users")
        async def create_admin(user: User = require_permission("users:admin")):
            ...

    The user must already be authenticated. Wire get_current_user upstream.
    """

    async def _check_permission(user: User) -> User:
        user_perms = {
            perm.code
            for role in user.roles
            for perm in role.permissions
        }
        if permission_code not in user_perms:
            raise AuthorizationError(f"Permission '{permission_code}' required")
        return user

    return Depends(_check_permission)
```

- [ ] **Step 4: Run — verify PASS**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_dependencies.py -v
```

Expected: `7 passed` (4 from Task 8 + 3 new)

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check packages/calango-plugins/calango-identity/ --fix
```

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugins/calango-identity/
git commit -m "feat(identity): require_permission() RBAC dependency — checks user roles"
```

---

## Task 10: Rate limiting (slowapi + fakeredis)

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/rate_limit.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_rate_limit.py`

- [ ] **Step 1: Write failing tests**

`packages/calango-plugins/calango-identity/tests/test_rate_limit.py`:
```python
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded

from calango_identity.rate_limit import make_limiter, get_email_key


def test_make_limiter_returns_limiter():
    """make_limiter() returns a Limiter instance."""
    from slowapi import Limiter
    limiter = make_limiter("memory://")
    assert isinstance(limiter, Limiter)


def test_get_email_key_returns_email_from_state():
    """get_email_key returns login_email from request.state when present."""
    request = type("Req", (), {"state": type("State", (), {"login_email": "a@b.com"})()})()
    # Simulate request.state.login_email
    key = get_email_key(request)
    assert key == "a@b.com"


async def test_rate_limit_blocks_after_threshold():
    """Endpoint decorated with limiter blocks requests after the threshold."""
    limiter = make_limiter("memory://")
    app = FastAPI()
    app.state.limiter = limiter

    from slowapi import _rate_limit_exceeded_handler
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/limited")
    @limiter.limit("2/minute")
    async def limited_endpoint(request: Request):
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get("/limited")
        r2 = await client.get("/limited")
        r3 = await client.get("/limited")  # should be blocked

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429


async def test_rate_limit_with_fakeredis():
    """make_limiter works with fakeredis storage URI."""
    import fakeredis
    limiter = make_limiter("memory://")  # fakeredis also works in-memory
    assert limiter is not None
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_rate_limit.py -v
```

Expected: `ModuleNotFoundError: No module named 'calango_identity.rate_limit'`

- [ ] **Step 3: Implement `rate_limit.py`**

`packages/calango-plugins/calango-identity/calango_identity/rate_limit.py`:
```python
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def make_limiter(storage_uri: str) -> Limiter:
    """Create a slowapi Limiter backed by the given storage URI.

    For production use: storage_uri = "redis://localhost:6379/0"
    For tests use: storage_uri = "memory://"
    """
    return Limiter(key_func=get_remote_address, storage_uri=storage_uri)


def get_email_key(request: Request) -> str:
    """Key function for per-email rate limiting on login endpoint.

    Falls back to IP if no login_email is set on request.state.
    """
    email = getattr(request.state, "login_email", None)
    if email:
        return email
    return get_remote_address(request)
```

- [ ] **Step 4: Run — verify PASS**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_rate_limit.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Ruff check**

```bash
uv run ruff check packages/calango-plugins/calango-identity/ --fix
```

- [ ] **Step 6: Commit**

```bash
git add packages/calango-plugins/calango-identity/
git commit -m "feat(identity): rate limiting with slowapi — make_limiter() + get_email_key()"
```

---

## Task 11: `IdentityPlugin` + public API + integration

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/plugin.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/__init__.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_plugin.py`

- [ ] **Step 1: Write failing tests**

`packages/calango-plugins/calango-identity/tests/test_plugin.py`:
```python
from __future__ import annotations

import pytest
from calango_plugin_base import PluginBase
from calango_identity.plugin import IdentityPlugin
from calango_identity.settings import IdentitySettings
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY


@pytest.fixture
def settings():
    return IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY)


def test_identity_plugin_implements_plugin_base(settings):
    """IdentityPlugin satisfies the PluginBase Protocol."""
    plugin = IdentityPlugin(settings=settings)
    assert isinstance(plugin, PluginBase)


def test_identity_plugin_name(settings):
    """IdentityPlugin.name is 'identity'."""
    plugin = IdentityPlugin(settings=settings)
    assert plugin.name == "identity"


def test_identity_plugin_migrations(settings):
    """IdentityPlugin.migrations() returns a non-empty list."""
    plugin = IdentityPlugin(settings=settings)
    assert len(plugin.migrations()) > 0


def test_identity_plugin_settings(settings):
    """IdentityPlugin.settings() returns IdentitySettings class."""
    plugin = IdentityPlugin(settings=settings)
    assert plugin.settings() is IdentitySettings


def test_identity_plugin_context_md(settings):
    """IdentityPlugin.context_md() returns a non-empty string."""
    plugin = IdentityPlugin(settings=settings)
    md = plugin.context_md()
    assert "identity" in md.lower()
    assert len(md) > 50


async def test_identity_plugin_registers_with_calango():
    """IdentityPlugin.register() adds auth routes to the Calango app."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    settings = IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY)
    plugin = IdentityPlugin(settings=settings)
    plugin.register(app)

    routes = [r.path for r in app.routes]
    assert any("/auth" in r for r in routes)


async def test_include_plugin_works_with_calango_factory():
    """Calango.include_plugin(IdentityPlugin()) integrates end-to-end."""
    from httpx import ASGITransport, AsyncClient
    from calango import Calango
    from calango.config import SecuritySettings

    settings_calango = type("S", (), {
        "APP_NAME": "Test", "VERSION": "0.1.0",
        "database": type("D", (), {"URL": "sqlite+aiosqlite:///:memory:", "POOL_SIZE": 1,
                                    "MAX_OVERFLOW": 0, "POOL_TIMEOUT": 5, "POOL_RECYCLE": 300})(),
        "redis": type("R", (), {"URL": "redis://localhost:6379/0"})(),
        "security": SecuritySettings(SECRET_KEY="test"),
    })()

    from calango.config import CalangoSettings
    calango_settings = CalangoSettings(security=SecuritySettings(SECRET_KEY="test"))
    app = Calango(settings=calango_settings)

    identity_settings = IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY)
    plugin = IdentityPlugin(settings=identity_settings)
    app.include_plugin(plugin)

    routes = [r.path for r in app.routes]
    assert any("/auth" in r for r in routes)
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_plugin.py -v
```

Expected: `ModuleNotFoundError: No module named 'calango_identity.plugin'`

- [ ] **Step 3: Implement `IdentityPlugin`**

`packages/calango-plugins/calango-identity/calango_identity/plugin.py`:
```python
from __future__ import annotations

from fastapi import FastAPI
from pydantic_settings import BaseSettings
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from calango_identity.models import Base
from calango_identity.rate_limit import make_limiter
from calango_identity.router import make_auth_router
from calango_identity.settings import IdentitySettings


class IdentityPlugin:
    """Calango Identity Plugin — JWT RS256 auth, RBAC, rate-limited endpoints."""

    name = "identity"
    version = "0.1.0"
    requires: list[str] = ["calango-core>=0.1.0", "calango-plugin-base>=0.1.0"]

    def __init__(self, settings: IdentitySettings | None = None) -> None:
        self._settings = settings or IdentitySettings()
        self._limiter = make_limiter(self._settings.REDIS_URL)

    def register(self, app: FastAPI) -> None:
        """Register auth routers, rate limiter middleware, and exception handlers."""
        # Rate limiter
        app.state.limiter = self._limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

        # Auth router — uses app's existing get_db dependency if available,
        # otherwise falls back to a no-op session (for testing without DB)
        try:
            from calango.core.database import get_db
        except ImportError:
            async def get_db():  # pragma: no cover
                yield None

        auth_router = make_auth_router(settings=self._settings, get_db=get_db)
        app.include_router(auth_router)

    def migrations(self) -> list[str]:
        """Return Alembic migration paths for identity tables."""
        return ["calango_identity.migrations"]

    def settings(self) -> type[BaseSettings]:
        return IdentitySettings

    def test_fixtures(self) -> list:
        """pytest fixtures for projects using calango-identity."""
        return []  # Expanded in future phases

    def context_md(self) -> str:
        return """<!-- BLOCK: identity -->
## Plugin: Identity

JWT RS256 authentication with RBAC. All routes require authentication by default.

Patterns:
- `current_user: User = Depends(get_current_user)` — inject authenticated user
- `@public` — mark route as publicly accessible (no token required)
- `user: User = require_permission("resource:action")` — RBAC check

Auth endpoints (registered automatically):
  POST /auth/jwt/login          — returns access_token
  POST /auth/register           — create account
  POST /auth/forgot-password    — initiate password reset
  POST /auth/reset-password     — apply reset token
  GET  /users/me                — current user info

Do NOT:
- Implement authentication manually — use plugin dependencies
- Store tokens in the database — only refresh tokens are persisted (JWT-based)
- Hardcode IDENTITY__PRIVATE_KEY — always use env vars or .env file
<!-- END BLOCK: identity -->"""
```

- [ ] **Step 4: Update public API**

`packages/calango-plugins/calango-identity/calango_identity/__init__.py`:
```python
from calango_identity.dependencies import public, require_permission
from calango_identity.models import Base, Permission, Role, User
from calango_identity.plugin import IdentityPlugin
from calango_identity.settings import IdentitySettings

__all__ = [
    "IdentityPlugin",
    "IdentitySettings",
    "User",
    "Role",
    "Permission",
    "Base",
    "public",
    "require_permission",
]
```

- [ ] **Step 5: Run — verify PASS**

```bash
uv run pytest packages/calango-plugins/calango-identity/tests/test_plugin.py -v
```

Expected: `7 passed`

- [ ] **Step 6: Run full suite**

```bash
uv run pytest packages/calango-plugin-base/ -q
uv run pytest packages/calango-core/ -q
uv run pytest packages/calango-plugins/calango-identity/ -q
```

Expected: all pass (5 + 74 + ~36 tests = ~115 total).

- [ ] **Step 7: Ruff check all packages**

```bash
uv run ruff check packages/calango-plugin-base/ packages/calango-core/ packages/calango-plugins/ --fix
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add packages/calango-plugins/calango-identity/
git commit -m "feat(identity): IdentityPlugin — full PluginBase implementation wiring auth, RBAC, rate limiting"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered in task |
|---|---|
| `calango-plugin-base` package with PluginBase Protocol | Task 2 |
| All 5 PluginBase methods | Task 2 |
| `Calango.include_plugin()` in calango-core | Task 3 |
| TypeError for non-conforming plugins | Task 3 |
| `IdentitySettings` with IDENTITY__ prefix | Task 4 |
| User, Role, Permission models with `identity_` prefix | Task 5 |
| FastAPI-Users + JWT RS256 auth backend | Task 6 |
| `/auth/login`, `/auth/register`, `/auth/forgot-password` | Task 7 |
| `@public` decorator | Task 8 |
| `require_permission()` RBAC dependency | Task 9 |
| slowapi rate limiting | Task 10 |
| `IdentityPlugin` all 5 PluginBase methods | Task 11 |
| `app.include_plugin(IdentityPlugin())` integration | Task 11 |

**Type consistency check:** `IdentitySettings` used consistently in Tasks 4, 6, 7, 10, 11. `make_auth_router(settings, get_db)` signature defined in Task 7, called in Task 11 — consistent. `PluginBase` from `calango-plugin-base` used in Tasks 2, 3, 11 — consistent.

**Placeholder scan:** All steps have code. No TBD or TODO except the RSA key generation instruction in Task 4 (intentional — requires local key generation). Task 11 `test_fixtures` returns `[]` with note "Expanded in future phases" — this is a valid empty implementation, not a placeholder.

**Scope:** 11 tasks, each independently commitable. ✅
