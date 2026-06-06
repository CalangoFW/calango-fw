# Calango Framework — Implementation Roadmap

> Status: Active development — started 2026-05-27
> Approach: Milestone-driven, TDD as default, solo + AI

---

## Macro Roadmap — 6 Milestones

| Milestone | Phases | Completion criteria |
|---|---|---|
| **M1** "calango new works" | 0 + 1 + 2 | `calango new my-api && docker compose up` → API on `:8000` |
| **M2** "generate resource" | 3 + 4 + 5 | `calango generate resource Shop.Product` → 9 files + tests running with real database |
| **M3** "minimal SaaS" | 6 | JWT auth + RBAC + all endpoints protected by default |
| **M4** "SaaS core" | 7 + 8 | Multi-tenant (RLS) + payments (Stripe + Pix) |
| **M5** "AI layer" | 9 | `calango generate agent Support` → agent running with MCP Server |
| **M6** "Ecosystem" | 10–13 | All plugins + published MkDocs docs |

---

## M1 — "calango new works"

Three sequential sub-phases. Result: anyone clones the repo, installs the CLI, and has a FastAPI project running in minutes.

---

### Phase 0: Monorepo Bootstrap ✅ Done

**Goal:** `uv sync` works, `uv run pytest` passes, `uv run ruff check .` passes.

**Structure created:**

```
calango_fw/
├── pyproject.toml                    # UV workspace root
├── ruff.toml                         # Shared lint/format config
├── .python-version                   # "3.12"
├── .gitignore
├── .pre-commit-config.yaml           # Hooks: ruff, ty
├── .github/
│   └── workflows/
│       └── ci.yml                    # Skeleton: lint + test
├── packages/
│   ├── calango-core/
│   │   ├── pyproject.toml            # deps: fastapi, pydantic-settings, sqlalchemy[asyncio]
│   │   └── calango/
│   │       └── __init__.py           # __version__ = "0.1.0-dev"
│   └── calango-cli/
│       ├── pyproject.toml            # deps: typer[all], jinja2, rich
│       └── calango_cli/
│           └── __init__.py
```

**pyproject.toml root:**
```toml
[tool.uv.workspace]
members = ["packages/*"]

[tool.uv]
dev-dependencies = ["pytest>=8", "pytest-asyncio", "httpx", "ruff", "ty", "pytest-cov"]
```

**Completion criteria:**
- `uv sync` without errors
- `uv run ruff check .` passes (0 errors)
- `uv run pytest packages/` passes (runner works)
- CI skeleton running on GitHub Actions

---

### Phase 1: calango-core base ✅ Done

**Goal:** The fundamental building blocks of the framework. All of Phase 2 (CLI) depends on them.

**TDD implementation order (test → implement → refactor):**

#### 1.1 — Exception hierarchy
`packages/calango-core/calango/exceptions/__init__.py`

```python
CalangoException(Exception)     # base — status_code, message, error_code
  ├── NotFoundError              # 404
  ├── ValidationError            # 422
  ├── AuthenticationError        # 401
  ├── AuthorizationError         # 403
  ├── ConflictError              # 409
  ├── RateLimitError             # 429 — with retry_after: int
  ├── ServiceUnavailableError    # 503
  └── ConfigurationError         # 500
```

Tests: `packages/calango-core/tests/test_exceptions.py` — 9 tests, one per type.

#### 1.2 — Base types
`packages/calango-core/calango/types/__init__.py`

```python
CalangoModel(BaseModel)           # Pydantic with from_attributes=True
PaginatedResponse[T](BaseModel)   # items, total, page, page_size, pages
OrderDirection(StrEnum)           # ASC = "asc", DESC = "desc"
```

Tests: `packages/calango-core/tests/test_types.py` — 5 tests.

#### 1.3 — CalangoSettings
`packages/calango-core/calango/config/__init__.py`

```python
class DatabaseSettings(BaseSettings):
    URL: str = "postgresql+asyncpg://..."
    POOL_SIZE: int = 10
    MAX_OVERFLOW: int = 20
    POOL_TIMEOUT: int = 30
    POOL_RECYCLE: int = 1800

class RedisSettings(BaseSettings):
    URL: str = "redis://localhost:6379/0"

class SecuritySettings(BaseSettings):
    SECRET_KEY: str                       # required, no default
    JWT_ALGORITHM: str = "RS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    CORS_ORIGINS: list[str] = []

class CalangoSettings(BaseSettings):
    APP_NAME: str = "Calango App"
    VERSION: str = "0.1.0"
    ENV: Literal["development", "production", "test"] = "development"
    DEBUG: bool = False
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    security: SecuritySettings

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
    )
```

Tests: `packages/calango-core/tests/test_config.py` — 3 tests.

#### 1.4 — Calango app factory
`packages/calango-core/calango/core/app.py`

```python
class Calango(FastAPI):
    def __init__(self, settings: CalangoSettings | None = None, **kwargs):
        # Configures title, version
        # Registers CalangoMiddleware
        # Registers global exception handlers
        ...
```

Tests: `packages/calango-core/tests/test_app.py` — 10 tests.

#### 1.5 — CalangoMiddleware
`packages/calango-core/calango/core/middleware.py`

- Injects `request.state.request_id = str(uuid4())`
- Adds security headers (X-Content-Type-Options, X-Frame-Options, HSTS, etc.)
- Injects `X-Calango-Version` header

#### 1.6 — Exception handlers
`packages/calango-core/calango/core/handlers.py`

- `CalangoException` → `{"error": error_code, "message": message, "request_id": ...}`
- Never exposes stack trace in production
- Generic exception → 500 with only `request_id`

#### 1.7 — Public API
`packages/calango-core/calango/__init__.py`

```python
__version__ = "0.1.0-dev"

from calango.core.app import Calango
from calango.config import CalangoSettings
from calango.types import CalangoModel, PaginatedResponse, OrderDirection
from calango.exceptions import (
    CalangoException, NotFoundError, ValidationError,
    AuthenticationError, AuthorizationError, ConflictError,
    RateLimitError, ServiceUnavailableError, ConfigurationError,
)
```

**Phase 1 result:** 54 tests passing · 97% coverage.

---

### Phase 2: calango-cli — calango new ✅ Done

**Goal:** `calango new my-api` generates a complete project that runs with `docker compose up`.

**CLI package structure:**

```
packages/calango-cli/
├── pyproject.toml
│   └── [project.scripts]
│       calango = "calango_cli.main:app"
└── calango_cli/
    ├── main.py              # Typer app root
    ├── commands/
    │   └── new.py           # calango new <name> [--db] [--agents] [--ci]
    └── templates/           # Jinja2 templates
        ├── app/
        ├── tests/
        ├── Dockerfile.jinja
        ├── compose.yml.jinja
        ├── CLAUDE.md.jinja
        └── ...
```

**20 artifacts generated by `calango new`:**

| # | File | Content |
|---|---|---|
| 1 | `app/__init__.py` | empty |
| 2 | `app/main.py` | `Calango()` with lifespan and settings |
| 3 | `app/core/__init__.py` | empty |
| 4 | `app/core/config.py` | `class Settings(CalangoSettings)` |
| 5 | `tests/__init__.py` | empty |
| 6 | `tests/conftest.py` | db + async client fixtures with rollback |
| 7 | `alembic/env.py` | configured for the project |
| 8 | `alembic.ini` | points to app.core.config |
| 9 | `Dockerfile` | 4 stages: base/development/ci/production |
| 10 | `compose.yml` | app + postgres + redis + minio |
| 11 | `.github/workflows/ci.yml` | 6 progressive gates |
| 12 | `.github/workflows/cd.yml` | staging → production with approval |
| 13 | `.github/pull_request_template.md` | Definition of Done checklist |
| 14 | `CLAUDE.md` | Generated with project-specific context |
| 15 | `.cursorrules` | Rules for Cursor |
| 16 | `pyproject.toml` | deps + ruff + pytest (80% coverage) |
| 17 | `.env.example` | all required variables |
| 18 | `.gitignore` | Python + UV + Docker standard |
| 19 | `CHANGELOG.md` | Keep a Changelog template |
| 20 | `SECURITY.md` | initial threat model |

**Phase 2 goal:** ≥37 tests passing. `curl localhost:8000/health` returns 200 after `docker compose up`.

---

## M2 — "generate resource"

### Phase 3: calango-core — BaseRepository + BaseService ✅ Done

`packages/calango-core/calango/repository/__init__.py`

```python
class BaseRepository(Generic[T]):
    async def get(self, id: UUID) -> T | None: ...
    async def list(self, *, skip: int = 0, limit: int = 100) -> list[T]: ...
    async def create(self, data: BaseModel) -> T: ...
    async def update(self, id: UUID, data: BaseModel) -> T: ...
    async def delete(self, id: UUID) -> None: ...
    async def get_for_update(self, id: UUID) -> T: ...  # SELECT FOR UPDATE
```

`packages/calango-core/calango/service/__init__.py`

```python
class BaseService(Generic[R]):
    def __init__(self, repository: R): ...

    @property
    def repository(self) -> R: ...
```

Includes: session DI factory (`get_db`), test utilities (`test_db_session`).

### Phase 4: calango-cli — generate resource ✅ Done

`calango generate resource <Context.Name>` generates 9 files (Phoenix-style contexts):

1. `app/contexts/<ctx>/models/<name>.py` — SQLAlchemy model
2. `app/contexts/<ctx>/schemas/<name>.py` — Input, Output, Update
3. `app/contexts/<ctx>/repositories/<name>.py` — extends BaseRepository
4. `app/contexts/<ctx>/services/<name>.py` — extends BaseService
5. `app/contexts/<ctx>/__init__.py` — context public API (created or re-rendered)
6. `app/routers/<name>.py` — FastAPI router, imports from context public API
7. `tests/unit/<ctx>/test_<name>_service.py` — 5 base cases with TODO
8. `tests/integration/<ctx>/test_<name>_router.py` — security cases (401, 403, BOLA)
9. `tests/factories/<name>_factory.py` — factory-boy

Pre-commit hook `calango-no-untested-resource`: fails if `app/contexts/<ctx>/services/X.py` exists without `tests/unit/<ctx>/test_X_service.py`.

### Phase 5: calango-cli — db commands 🟡 Next

```bash
calango db migrate          # wrapper: uv run alembic upgrade head
calango db seed             # runs app/seeds/ in order
calango db rollback         # uv run alembic downgrade -1
calango db suggest-indexes  # analyzes pg_stat_statements, suggests + generates migration
```

---

## M3 — "minimal SaaS"

### Phase 6: calango-identity 🟡 Mostly done — refresh-token rotation pending

`packages/calango-plugins/calango-identity/`

- Base: FastAPI-Users + JWT RS256 (asymmetric)
- Endpoints: `POST /auth/login`, `/auth/register`, `/auth/refresh`, `/auth/forgot-password`
- `@public` decorator for public endpoints
- `@require_permission("resource:action")` for RBAC
- Rate limit on `/auth`: 5/min per IP, 10/hour per email
- JWT: access=15min, refresh=7 days with rotation
- Argon2 for password hashing

---

## M4 — "SaaS core"

### Phase 7: calango-multitenancy

`packages/calango-plugins/calango-multitenancy/`

- Row-level (default): RLS via Postgres, `tenant_id` injected automatically
- `@tenantable` decorator on the model
- Resolution: subdomain → JWT claim → `X-Tenant-ID` header
- Schema-level as option (`--mode=schema`)

### Phase 8: calango-payments

`packages/calango-plugins/calango-payments/`

- Abstraction over Stripe and MercadoPago (common interface)
- Webhooks with mandatory HMAC verification
- Idempotency via `Idempotency-Key` header

---

## M5 — "AI layer"

### Phase 9: calango-agents

`packages/calango-plugins/calango-agents/`

- Agno v2.6+ as default engine
- `AgentRouter` + decorators `@router.agent()` + `@router.tool()`
- Tool Registry with automatic Pydantic schema
- MCP Server exposed at `/mcp`
- `AgentContext` injected automatically (user_id, tenant_id, permissions)
- Human-in-the-loop via `requires_approval=True`

---

## M6 — "Ecosystem"

### Phase 10: Productivity plugins
- `calango-search` — PG FTS (default), Typesense, Meilisearch
- `calango-notifications` — email, push, SMS, Slack, outbound webhook
- `calango-admin` — SQLAdmin + Admin Copilot (NL2SQL)
- `calango-media` — S3/GCS/MinIO, async conversions
- `calango-background` — ARQ (default), Celery, automatic DLQ

### Phase 11: Model mixins
`soft-delete`, `audit-log`, `sluggable`, `sortable`, `nested-tree`, `taggable`

### Phase 12: Advanced SaaS
`calango-plans`, `calango-feature-flags`, `calango-teams`

### Phase 13: DX and documentation
- `calango context` — auto-regenerates CLAUDE.md
- ✅ `calango check:security` — SAST (Opengrep) + SCA (pip-audit) gate, in framework and generated projects
- MkDocs Material — published documentation

---

## M1 end-to-end verification

```bash
# Setup
uv sync
uv run pytest packages/ -v       # all tests pass
uv run ruff check .               # 0 errors

# Scaffold
uv run calango new my-api --path /tmp
cd /tmp/my-api

# Verify artifacts
ls app/ tests/ compose.yml Dockerfile CLAUDE.md .github/

# Start environment
docker compose up -d
curl http://localhost:8000/health  # → {"status": "ok", "version": "0.1.0"}

# Verify security headers
curl -I http://localhost:8000/health | grep -E "X-Content-Type|X-Frame|Strict-Transport"

# Verify generated project
uv run pytest          # fixtures load
uv run ruff check .    # 0 errors
```

---

## Immutable conventions

Defined in `CLAUDE.md` — non-negotiable:

- **Minimum Python:** 3.12
- **Stack:** FastAPI + Pydantic v2 + SQLAlchemy 2 async + UV
- **Architecture:** `routers → services → repositories → models` (no skipping layers)
- **Schemas:** mandatory suffixes `Input`, `Output`, `Update`
- **Tests:** descriptive names that document the business rule
- **Coverage:** 80% gate in CI (fails below that)
- **Commits:** Conventional Commits enforced
- **Security:** never expose stack trace in production, never hardcode secrets
