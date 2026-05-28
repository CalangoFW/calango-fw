# Calango Framework — Roadmap de Implementação

> Status: Em desenvolvimento ativo — iniciado em 2026-05-27
> Abordagem: Milestone-driven, TDD como padrão, solo + IA

---

## Macro Roadmap — 6 Milestones

| Milestone | Fases | Critério de conclusão |
|---|---|---|
| **M1** "calango new roda" | 0 + 1 + 2 | `calango new minha-api && docker compose up` → API em `:8000` |
| **M2** "generate resource" | 3 + 4 + 5 | `calango generate resource Produto` → 8 arquivos + testes rodando com banco real |
| **M3** "SaaS mínimo" | 6 | Auth JWT + RBAC + todos os endpoints protegidos por padrão |
| **M4** "SaaS core" | 7 + 8 | Multi-tenant (RLS) + pagamentos (Stripe + Pix) |
| **M5** "AI layer" | 9 | `calango generate agent Suporte` → agente rodando com MCP Server |
| **M6** "Ecosystem" | 10–13 | Todos os plugins + docs MkDocs publicados |

---

## M1 — "calango new roda"

Três sub-fases sequenciais. Resultado: qualquer pessoa clona o repo, instala o CLI e tem um projeto FastAPI rodando em minutos.

---

### Fase 0: Bootstrap do Monorepo

**Objetivo:** `uv sync` funciona, `uv run pytest` passa, `uv run ruff check .` passa.

**Estrutura a criar:**

```
calango_fw/
├── pyproject.toml                    # UV workspace root
├── ruff.toml                         # Config compartilhada lint/format
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
dev-dependencies = ["pytest>=8", "pytest-asyncio", "httpx", "ruff", "ty"]
```

**Critério de conclusão:**
- `uv sync` sem erros
- `uv run ruff check .` passa (0 erros)
- `uv run pytest packages/` passa (runner funciona)
- CI skeleton rodando no GitHub Actions

---

### Fase 1: calango-core base

**Objetivo:** Blocos fundamentais do framework. Toda a Fase 2 (CLI) depende deles.

**Ordem de implementação TDD (teste → implementação → refatorar):**

#### 1.1 — Hierarquia de exceções
`packages/calango-core/calango/exceptions/__init__.py`

```python
CalangoException(Exception)     # base — status_code, message, error_code
  ├── NotFoundError              # 404
  ├── ValidationError            # 422
  ├── AuthenticationError        # 401
  ├── AuthorizationError         # 403
  ├── ConflictError              # 409
  ├── RateLimitError             # 429 — com retry_after: int
  ├── ServiceUnavailableError    # 503
  └── ConfigurationError         # 500
```

Testes: `packages/calango-core/tests/test_exceptions.py` — 9 testes, um por tipo.

#### 1.2 — Tipos base
`packages/calango-core/calango/types/__init__.py`

```python
CalangoModel(BaseModel)           # Pydantic com from_attributes=True
PaginatedResponse[T](BaseModel)   # items, total, page, page_size, pages
OrderDirection(str, Enum)         # ASC = "asc", DESC = "desc"
```

Testes: `packages/calango-core/tests/test_types.py` — 5 testes.

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
    SECRET_KEY: str                       # obrigatório, sem default
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

Testes: `packages/calango-core/tests/test_config.py` — 3 testes.

#### 1.4 — Calango app factory
`packages/calango-core/calango/core/app.py`

```python
class Calango(FastAPI):
    def __init__(self, settings: CalangoSettings | None = None, **kwargs):
        # Configura title, version, lifespan
        # Registra CalangoMiddleware
        # Registra exception handlers globais
        ...

    def include_plugin(self, plugin: PluginBase) -> None: ...
```

Testes: `packages/calango-core/tests/test_app.py` — 3 testes.

#### 1.5 — CalangoMiddleware
`packages/calango-core/calango/core/middleware.py`

- Injeta `request.state.request_id = str(uuid4())`
- Adiciona headers de segurança (X-Content-Type-Options, X-Frame-Options, HSTS, etc.)
- Loga request + response em JSON estruturado (sem PII)
- Injeta `X-Calango-Version` header

#### 1.6 — Exception handlers
`packages/calango-core/calango/core/handlers.py`

- `CalangoException` → `{"error": error_code, "message": message, "request_id": ...}`
- Nunca expõe stack trace em production
- Exception genérica → 500 com só `request_id`

#### 1.7 — API pública
`packages/calango-core/calango/__init__.py`

```python
__version__ = "0.1.0"

from calango.core.app import Calango
from calango.config import CalangoSettings
from calango.types import CalangoModel, PaginatedResponse, OrderDirection
from calango.exceptions import (
    CalangoException, NotFoundError, ValidationError,
    AuthenticationError, AuthorizationError, ConflictError,
    RateLimitError, ServiceUnavailableError, ConfigurationError,
)
```

**Meta Fase 1:** ≥20 testes passando, cobertura ≥80%.

---

### Fase 2: calango-cli — calango new

**Objetivo:** `calango new minha-api` gera projeto completo que roda com `docker compose up`.

**Estrutura do pacote CLI:**

```
packages/calango-cli/
├── pyproject.toml
│   └── [project.scripts]
│       calango = "calango_cli.main:app"
└── calango_cli/
    ├── main.py              # Typer app root
    ├── commands/
    │   └── new.py           # calango new <nome> [--db] [--agents] [--ci]
    └── templates/           # Jinja2 templates
        ├── app/
        ├── tests/
        ├── Dockerfile.jinja
        ├── compose.yml.jinja
        ├── CLAUDE.md.jinja
        └── ...
```

**20 artefatos gerados por `calango new`:**

| # | Arquivo | Conteúdo |
|---|---|---|
| 1 | `app/__init__.py` | vazio |
| 2 | `app/main.py` | `Calango()` com lifespan e settings |
| 3 | `app/core/__init__.py` | vazio |
| 4 | `app/core/config.py` | `class Settings(CalangoSettings)` |
| 5 | `tests/__init__.py` | vazio |
| 6 | `tests/conftest.py` | fixtures db + client async com rollback |
| 7 | `alembic/env.py` | configurado para o projeto |
| 8 | `alembic.ini` | aponta para app.core.config |
| 9 | `Dockerfile` | 4 stages: base/development/ci/production |
| 10 | `compose.yml` | app + postgres + redis + minio |
| 11 | `.github/workflows/ci.yml` | 6 gates progressivos |
| 12 | `.github/workflows/cd.yml` | staging → production com aprovação |
| 13 | `.github/pull_request_template.md` | Definition of Done checklist |
| 14 | `CLAUDE.md` | Gerado com contexto específico do projeto |
| 15 | `.cursorrules` | Regras para Cursor |
| 16 | `pyproject.toml` | deps + ruff + pytest (coverage 80%) |
| 17 | `.env.example` | todas as variáveis necessárias |
| 18 | `.gitignore` | Python + UV + Docker padrão |
| 19 | `CHANGELOG.md` | template Keep a Changelog |
| 20 | `SECURITY.md` | threat model inicial |

**Meta Fase 2:** ≥37 testes passando. `curl localhost:8000/health` retorna 200 após `docker compose up`.

---

## M2 — "generate resource"

### Fase 3: calango-core — BaseRepository + BaseService

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

Inclui: session DI factory (`get_db`), test utilities (`test_db_session`).

### Fase 4: calango-cli — generate resource

`calango generate resource <Nome>` gera 8 arquivos:

1. `app/models/<nome>.py` — SQLAlchemy model
2. `app/schemas/<nome>.py` — Input, Output, Update
3. `app/repositories/<nome>.py` — herda BaseRepository
4. `app/services/<nome>.py` — herda BaseService
5. `app/routers/<nome>.py` — FastAPI router
6. `tests/unit/test_<nome>_service.py` — 5 casos base com TODO
7. `tests/integration/test_<nome>_router.py` — casos de segurança (401, 403, BOLA)
8. `tests/factories/<nome>_factory.py` — factory-boy

Pre-commit hook `calango-no-untested-resource`: falha se `app/services/X.py` existe sem `tests/unit/test_X_service.py`.

### Fase 5: calango-cli — db commands

```bash
calango db migrate          # wrapper: uv run alembic upgrade head
calango db seed             # executa app/seeds/ em ordem
calango db rollback         # uv run alembic downgrade -1
calango db suggest-indexes  # analisa pg_stat_statements, sugere + gera migration
```

---

## M3 — "SaaS mínimo"

### Fase 6: calango-identity

`packages/calango-plugins/calango-identity/`

- Base: FastAPI-Users + JWT RS256 (assimétrico)
- Endpoints: `POST /auth/login`, `/auth/register`, `/auth/refresh`, `/auth/forgot-password`
- `@public` decorator para endpoints públicos
- `@require_permission("resource:action")` para RBAC
- Rate limit em `/auth`: 5/min por IP, 10/hour por email
- JWT: access=15min, refresh=7 dias com rotation
- Argon2 para hash de senhas

---

## M4 — "SaaS core"

### Fase 7: calango-multitenancy

`packages/calango-plugins/calango-multitenancy/`

- Row-level (padrão): RLS via Postgres, `tenant_id` injetado automaticamente
- `@tenantable` decorator no model
- Resolução: subdomain → JWT claim → header `X-Tenant-ID`
- Schema-level como opção (`--mode=schema`)

### Fase 8: calango-payments

`packages/calango-plugins/calango-payments/`

- Abstração sobre Stripe e MercadoPago (interface comum)
- Webhooks com verificação HMAC obrigatória
- Idempotência por `Idempotency-Key` header

---

## M5 — "AI layer"

### Fase 9: calango-agents

`packages/calango-plugins/calango-agents/`

- Agno v2.6+ como engine padrão
- `AgentRouter` + decorators `@router.agent()` + `@router.tool()`
- Tool Registry com schema Pydantic automático
- MCP Server exposto em `/mcp`
- `AgentContext` injetado automaticamente (user_id, tenant_id, permissions)
- Human-in-the-loop via `requires_approval=True`

---

## M6 — "Ecosystem"

### Fase 10: Plugins de produtividade
- `calango-search` — PG FTS (padrão), Typesense, Meilisearch
- `calango-notifications` — email, push, SMS, Slack, webhook outbound
- `calango-admin` — SQLAdmin + Admin Copilot (NL2SQL)
- `calango-media` — S3/GCS/MinIO, conversões async
- `calango-background` — ARQ (padrão), Celery, DLQ automática

### Fase 11: Model mixins
`soft-delete`, `audit-log`, `sluggable`, `sortable`, `nested-tree`, `taggable`

### Fase 12: SaaS avançado
`calango-plans`, `calango-feature-flags`, `calango-teams`

### Fase 13: DX e documentação
- `calango context` — regenera CLAUDE.md automaticamente
- `calango check:security` — auditoria pré-deploy
- MkDocs Material — documentação publicada

---

## Verificação end-to-end do M1

```bash
# Setup
uv sync
uv run pytest packages/ -v       # todos os testes passam
uv run ruff check .               # 0 erros

# Scaffold
uv run calango new minha-api --path /tmp
cd /tmp/minha-api

# Verificar artefatos
ls app/ tests/ compose.yml Dockerfile CLAUDE.md .github/

# Subir ambiente
docker compose up -d
curl http://localhost:8000/health  # → {"status": "ok", "version": "0.1.0"}

# Verificar headers de segurança
curl -I http://localhost:8000/health | grep -E "X-Content-Type|X-Frame|Strict-Transport"

# Verificar projeto gerado
uv run pytest          # fixtures carregam
uv run ruff check .    # 0 erros
```

---

## Convenções imutáveis

Definidas no `CLAUDE.md` — não negociáveis:

- **Python mínimo:** 3.12
- **Stack:** FastAPI + Pydantic v2 + SQLAlchemy 2 async + UV
- **Arquitetura:** `routers → services → repositories → models` (sem saltar camadas)
- **Schemas:** sufixos obrigatórios `Input`, `Output`, `Update`
- **Testes:** nomes descritivos que documentam a regra de negócio
- **Coverage:** gate de 80% no CI (falha abaixo disso)
- **Commits:** Conventional Commits enforçados
- **Segurança:** nunca expor stack trace em production, nunca hardcode secrets
