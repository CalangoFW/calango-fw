# Calango Identity — Design Spec

> Phase 6 — M3 "minimal SaaS"
> Status: Approved for implementation

---

## Overview

`calango-identity` is the first official Calango plugin, delivering JWT RS256 authentication, RBAC, and rate-limited auth endpoints as a first-class framework primitive.

Phase 6 delivers three things in order:

1. **`calango-plugin-base`** — the shared `PluginBase` Protocol (contract all plugins implement)
2. **`calango-core` update** — `Calango.include_plugin()` method
3. **`calango-identity`** — FastAPI-Users + JWT RS256 + Argon2 + Redis rate limiting + RBAC

---

## Package Architecture

```
packages/
├── calango-core/                      # existing — add include_plugin()
├── calango-cli/                       # existing — no changes
├── calango-plugin-base/               # NEW
│   ├── pyproject.toml
│   └── calango_plugin_base/
│       ├── __init__.py                # PluginBase Protocol
│       └── tests/
│           └── test_plugin_base.py
└── calango-plugins/
    └── calango-identity/              # NEW
        ├── pyproject.toml
        └── calango_identity/
            ├── __init__.py            # public API
            ├── plugin.py              # IdentityPlugin(PluginBase)
            ├── models.py              # User, Role, Permission, junction tables
            ├── schemas.py             # UserRead, UserCreate, UserUpdate
            ├── router.py              # /auth/login, /register, /refresh, /forgot-password
            ├── dependencies.py        # get_current_user, @public, @require_permission
            ├── security.py            # JWT RS256 strategy + key utilities
            ├── rate_limit.py          # slowapi + Redis limiter
            ├── settings.py            # IdentitySettings
            └── tests/
                ├── conftest.py
                ├── test_plugin.py
                ├── test_auth_router.py
                ├── test_dependencies.py
                └── test_rate_limit.py
```

---

## Part 1: `calango-plugin-base`

### PluginBase Protocol

```python
# calango_plugin_base/__init__.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import FastAPI
from pydantic_settings import BaseSettings


@runtime_checkable
class PluginBase(Protocol):
    """Contract every Calango plugin must implement."""

    name: str           # slug identifier: "identity", "payments"
    version: str        # semver: "0.1.0"
    requires: list[str] # dep constraints: ["calango-core>=0.1.0"]

    def register(self, app: FastAPI) -> None:
        """Register routers, middleware, exception handlers, and lifecycle hooks."""
        ...

    def migrations(self) -> list[str]:
        """Return Alembic migration module paths contributed by this plugin."""
        ...

    def settings(self) -> type[BaseSettings]:
        """Return the plugin's settings class (pydantic-settings subclass)."""
        ...

    def test_fixtures(self) -> list:
        """Return pytest fixtures injected into projects using this plugin."""
        ...

    def context_md(self) -> str:
        """Return a CLAUDE.md block describing the plugin for AI assistants."""
        ...
```

**Dependencies:** `fastapi>=0.115`, `pydantic-settings>=2.6`

**Tests:** verify `isinstance(plugin, PluginBase)` works at runtime, verify protocol enforcement.

---

## Part 2: `calango-core` update

### `Calango.include_plugin()`

Add to `packages/calango-core/calango/core/app.py`:

```python
from calango_plugin_base import PluginBase

class Calango(FastAPI):
    def __init__(self, ...):
        ...  # existing

    def include_plugin(self, plugin: PluginBase) -> None:
        """Register a Calango plugin. Calls plugin.register(self)."""
        if not isinstance(plugin, PluginBase):
            raise TypeError(
                f"{type(plugin).__name__} does not implement PluginBase. "
                "All 5 methods (register, migrations, settings, test_fixtures, context_md) "
                "must be defined."
            )
        plugin.register(self)
```

**Tests:** verify `include_plugin()` calls `plugin.register()`, verify `TypeError` on non-conforming objects.

---

## Part 3: `calango-identity`

### Settings

```python
# calango_identity/settings.py
class IdentitySettings(BaseSettings):
    PRIVATE_KEY: str              # RSA private key PEM — required, no default
    PUBLIC_KEY: str               # RSA public key PEM — required, no default
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 5
    RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL: int = 10
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_prefix="IDENTITY__")
```

RSA key pair generation helper (dev convenience):
```bash
# .env.example for projects using calango-identity
# Generate with: openssl genrsa -out private.pem 2048 && openssl rsa -in private.pem -pubout -out public.pem
IDENTITY__PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
IDENTITY__PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n..."
```

### Models

```python
# calango_identity/models.py
from fastapi_users.db import SQLAlchemyBaseUserTableUUID

class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "identity_users"
    # FastAPI-Users provides: id, email, hashed_password, is_active, is_superuser, is_verified
    roles: Mapped[list[Role]] = relationship(secondary="identity_user_roles", lazy="selectin")

class Role(Base):
    __tablename__ = "identity_roles"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    permissions: Mapped[list[Permission]] = relationship(
        secondary="identity_role_permissions", lazy="selectin"
    )

class Permission(Base):
    __tablename__ = "identity_permissions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True)  # "orders:read"

# Junction tables (association only, no extra columns)
user_roles = Table("identity_user_roles", Base.metadata,
    Column("user_id", ForeignKey("identity_users.id"), primary_key=True),
    Column("role_id", ForeignKey("identity_roles.id"), primary_key=True),
)
role_permissions = Table("identity_role_permissions", Base.metadata,
    Column("role_id", ForeignKey("identity_roles.id"), primary_key=True),
    Column("permission_id", ForeignKey("identity_permissions.id"), primary_key=True),
)
```

All tables prefixed with `identity_` to avoid collisions with application tables.

### Auth Backend (JWT RS256)

```python
# calango_identity/security.py
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy

def make_auth_backend(settings: IdentitySettings) -> AuthenticationBackend:
    return AuthenticationBackend(
        name="jwt",
        transport=BearerTransport(tokenUrl="/auth/login"),
        get_strategy=lambda: JWTStrategy(
            secret=settings.PRIVATE_KEY,
            lifetime_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            algorithm="RS256",
            public_key=settings.PUBLIC_KEY,
        ),
    )
```

### Rate Limiting

```python
# calango_identity/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

def make_limiter(redis_url: str) -> Limiter:
    return Limiter(key_func=get_remote_address, storage_uri=redis_url)

def get_email_key(request: Request) -> str:
    """Key function for per-email rate limiting."""
    body = getattr(request.state, "parsed_body", {})
    return body.get("username", get_remote_address(request))
```

Applied to endpoints:
```python
@router.post("/login")
@limiter.limit("5/minute")
@limiter.limit("10/hour", key_func=get_email_key)
async def login(credentials: OAuth2PasswordRequestForm = Depends()): ...
```

### `@public` and `@require_permission`

```python
# calango_identity/dependencies.py

# Sentinel dependency — overridden globally by IdentityPlugin.register()
_CURRENT_USER_DEP = Annotated[User | None, Depends(lambda: None)]

def public(func: Callable) -> Callable:
    """Mark a route as not requiring authentication."""
    func.__calango_public__ = True
    return func

async def get_current_user(
    request: Request,
    user: User | None = Depends(_optional_fastapi_users_dep),
) -> User | None:
    if getattr(request.scope.get("endpoint"), "__calango_public__", False):
        return None
    if user is None:
        raise AuthenticationError("Authentication required")
    return user

def require_permission(permission_code: str) -> Depends:
    """RBAC dependency — use as a default parameter value."""
    async def _check(user: User = Depends(get_current_user)) -> User:
        user_perms = {
            perm.code
            for role in user.roles
            for perm in role.permissions
        }
        if permission_code not in user_perms:
            raise AuthorizationError(f"Permission '{permission_code}' required")
        return user
    return Depends(_check)
```

Usage:
```python
@router.get("/health")
@public
async def health(): ...

@router.post("/admin/users")
async def create_admin(user: User = require_permission("users:admin")): ...
```

### Auth Endpoints

```python
# calango_identity/router.py — generated by FastAPI-Users + custom additions
POST   /auth/login             # OAuth2 password flow → access + refresh tokens
POST   /auth/register          # create account
POST   /auth/refresh           # exchange refresh token → new access token
POST   /auth/logout            # invalidate refresh token
POST   /auth/forgot-password   # send reset email
POST   /auth/reset-password    # apply reset token
GET    /auth/me                # current user info
```

### `IdentityPlugin`

```python
# calango_identity/plugin.py
class IdentityPlugin:
    name = "identity"
    version = "0.1.0"
    requires = ["calango-core>=0.1.0", "calango-plugin-base>=0.1.0"]

    def __init__(self, settings: IdentitySettings | None = None) -> None:
        self._settings = settings or IdentitySettings()
        self._limiter = make_limiter(self._settings.REDIS_URL)
        self._auth_backend = make_auth_backend(self._settings)
        self._fastapi_users = make_fastapi_users(self._auth_backend)

    def register(self, app: FastAPI) -> None:
        # Rate limiter
        app.state.limiter = self._limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        # Auth routers
        app.include_router(
            self._fastapi_users.get_auth_router(self._auth_backend),
            prefix="/auth", tags=["auth"],
        )
        app.include_router(
            self._fastapi_users.get_register_router(UserRead, UserCreate),
            prefix="/auth", tags=["auth"],
        )
        app.include_router(
            self._fastapi_users.get_reset_password_router(),
            prefix="/auth", tags=["auth"],
        )
        app.include_router(
            self._fastapi_users.get_users_router(UserRead, UserUpdate),
            prefix="/users", tags=["users"],
        )

    def migrations(self) -> list[str]:
        return ["calango_identity.migrations"]

    def settings(self) -> type[IdentitySettings]:
        return IdentitySettings

    def test_fixtures(self) -> list:
        return [create_user, auth_headers, superuser_headers]

    def context_md(self) -> str:
        return """<!-- BLOCK: identity -->
## Plugin: Identity

JWT RS256 authentication. All routes require auth by default.

Patterns:
- `current_user: User = Depends(get_current_user)` — inject authenticated user
- `@public` — mark route as public (no auth required)
- `user: User = require_permission("resource:action")` — RBAC check

Endpoints: POST /auth/login, /auth/register, /auth/refresh, /auth/logout,
           /auth/forgot-password, /auth/reset-password, GET /auth/me

Do NOT:
- Implement auth manually — use plugin dependencies
- Store tokens in the database — only refresh tokens are persisted
<!-- END BLOCK: identity -->"""
```

---

## Dependencies

**`calango-plugin-base`:** `fastapi>=0.115`, `pydantic-settings>=2.6`

**`calango-identity`:**
```toml
dependencies = [
    "calango-plugin-base>=0.1.0",
    "fastapi-users[sqlalchemy]>=13",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
    "slowapi>=0.1.9",
    "redis>=5.2",
    "argon2-cffi>=23",            # FastAPI-Users uses this via passlib
]
```

---

## Testing Strategy

- **`calango-plugin-base`**: pure unit tests — protocol conformance, runtime checking
- **`calango-core` update**: unit test `include_plugin()` with mock plugin
- **`calango-identity`**:
  - Auth router tests: SQLite + aiosqlite (no Docker needed for unit)
  - Rate limit tests: mock Redis with `fakeredis`
  - RBAC tests: create user with roles, assert 403 vs 200
  - `@public` tests: verify unauthenticated access allowed
  - Integration: pytest-asyncio + ASGI test client (httpx)

Target: ≥30 new tests across the 3 packages.

---

## Delivery Milestones

| Step | What | Tests |
|------|------|-------|
| 1 | `calango-plugin-base` package + `PluginBase` Protocol | 5 |
| 2 | `calango-core`: `include_plugin()` + tests | 3 |
| 3 | `calango-identity`: models + settings + migrations | 8 |
| 4 | `calango-identity`: auth backend + router (FastAPI-Users) | 10 |
| 5 | `calango-identity`: `@public` + `require_permission` + RBAC | 8 |
| 6 | `calango-identity`: rate limiting (slowapi + Redis/fakeredis) | 6 |
| 7 | `IdentityPlugin.register()` + integration wiring | 5 |

---

## Usage (final state)

```python
# app/main.py — generated by calango new after plugin add
from calango import Calango
from calango_identity import IdentityPlugin
from app.core.config import Settings

settings = Settings()
app = Calango(settings=settings)
app.include_plugin(IdentityPlugin())

# All endpoints now require auth. Public endpoints need @public:
@app.get("/health")
@public
async def health():
    return {"status": "ok"}
```

```bash
# .env
IDENTITY__PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
IDENTITY__PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n..."
IDENTITY__REDIS_URL=redis://localhost:6379/0
```
