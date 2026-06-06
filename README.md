<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/calango-mark-white-transparent-1024.png">
  <img src="docs/assets/calango-mark-green-transparent-1024.png" alt="Calango" width="96">
</picture>

# calango

**The fast, friendly Python web framework.**

[![Python](https://img.shields.io/badge/python-3.12+-2CBD6B?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-2CBD6B?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-PolyForm%20NonCommercial-2CBD6B?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/status-early%20development-E29A2E?style=flat-square)]()
[![Tests](https://img.shields.io/badge/tests-161%20passing-2CBD6B?style=flat-square)]()

*Convention over Configuration. TDD as the default path. AI as a first-class citizen.*

</div>

---

> **Early development.** The core package is functional. The CLI and plugins are planned — see [Roadmap](#roadmap).

---

## What is Calango?

Calango is an **API-first** Python meta-framework for web development inspired by **Phoenix Framework** and **Nest.js** — with Rails' opinionated structure and FastAPI's async core.

The premise: you shouldn't spend energy deciding where to put each file, how to configure CI, or how to structure your tests. Calango decides that for you — and when you need to deviate from the convention, the exit is explicit and documented.

```bash
# Coming soon (CLI in development):
pip install calango
calango new my-project
cd my-project && docker compose up
```

In under two minutes you get a project with database, cache, storage, CI/CD, `CLAUDE.md` for your AI assistants, and tests ready to write.


---

## Why Calango?

### For the Python developer

Python dominates AI and ML. FastAPI dominates APIs. But no Python framework treats **AI-assisted development** as a design principle — or makes **TDD the path of least resistance**.

Calango was designed from scratch for developers who use Claude Code, Cursor, Codex, or Copilot daily:

- **Predictable structure as a contract** — any AI opens your project and knows where everything lives
- **`CLAUDE.md` generated and auto-maintained** — always up-to-date context for your assistants
- **Tests generated alongside code** — not as a separate step
- **AI agents as a framework primitive** — not a third-party plugin bolted on

### Convention over Configuration — but flexible

```bash
# Happy path: zero configuration
calango generate resource Shop.Order
# Creates in app/contexts/shop/: model + schema + repository + service
# Creates in app/routers/: router
# Creates in tests/: unit/shop/ + integration/shop/ + factory

# Need to deviate? It's explicit:
# Create elsewhere — the framework won't block you,
# it just won't guide you automatically.
```

### Batteries included, not forced

Activate what you need, when you need it:

```bash
calango plugin add identity      # JWT, OAuth2, RBAC
calango plugin add payments      # Stripe, Pix, webhooks
calango plugin add agents        # AI agents with Agno
calango plugin add multitenancy  # Row-level security on Postgres
calango plugin add search        # FTS, Typesense, Meilisearch
```

---

## What works today

`calango-core` is fully implemented with 54 tests and 97% coverage. `calango-cli` (`calango new` + `calango generate resource`) is implemented with 107 tests.

### App factory with built-in security

```python
from calango import Calango, CalangoSettings
from calango.config import SecuritySettings

settings = CalangoSettings(
    APP_NAME="My API",
    security=SecuritySettings(SECRET_KEY="your-key"),
)
app = Calango(settings=settings)

@app.get("/products/{id}")
def get_product(id: str):
    return {"id": id}
```

Every response automatically includes security headers — no configuration needed:

```
x-request-id: 3f2a1b4c-...        ← unique UUID per request
x-calango-version: 0.1.0-dev
x-content-type-options: nosniff
x-frame-options: DENY
strict-transport-security: max-age=31536000
```

### Structured error responses

```python
from calango.exceptions import NotFoundError, AuthorizationError, ConflictError

@app.get("/products/{id}")
def get_product(id: str):
    raise NotFoundError("Product not found")
    # → HTTP 404: {"error": "not_found", "message": "Product not found", "request_id": "..."}

@app.post("/users")
def create_user(email: str):
    raise ConflictError("Email already registered")
    # → HTTP 409

# Unhandled RuntimeError or any exception → 500 with no stack trace exposed
```

Nine exception types: `NotFoundError`, `ValidationError`, `AuthenticationError`, `AuthorizationError`, `ConflictError`, `RateLimitError`, `ServiceUnavailableError`, `ConfigurationError` — all producing consistent JSON.

### Pydantic base models

```python
from calango import CalangoModel, PaginatedResponse, OrderDirection

class ProductOutput(CalangoModel):   # from_attributes=True — ORM-ready
    id: int
    name: str
    price: float

@app.get("/products")
def list_products() -> PaginatedResponse[ProductOutput]:
    return PaginatedResponse(
        items=[ProductOutput(id=1, name="T-Shirt", price=49.90)],
        total=1, page=1, page_size=10  # pages computed automatically
    )
```

### Settings from environment

```python
# All sub-settings configurable via env vars or .env file
settings = CalangoSettings(
    APP_NAME="My API",
    security=SecuritySettings(SECRET_KEY="..."),
    # database, redis sub-settings auto-populated from env
)
```

```bash
APP_NAME="Store API" SECURITY__SECRET_KEY="key" uv run uvicorn app:app
```

### 🏗️ Full scaffold in one command

```bash
calango new my-api --db=postgres --ci=github --agents

# Generates in ~45 seconds:
# ✓ CoC directory structure
# ✓ Multi-stage Dockerfile (dev/ci/production)
# ✓ Docker Compose with postgres, redis, minio, ollama
# ✓ GitHub Actions CI (6 progressive gates) + CD
# ✓ PR template with Definition of Done
# ✓ CLAUDE.md for Claude Code, .cursorrules for Cursor
# ✓ Git initialized with Conventional Commits enforced
# ✓ pyproject.toml with 80% coverage gate
# ✓ SAST + SCA security gate (Ruff S + Opengrep + pip-audit)
```

### 🧪 TDD as the path of least resistance

```bash
calango generate resource Shop.Order

# Creates alongside the code (9 files total):
# app/contexts/shop/models/order.py
# app/contexts/shop/schemas/order.py
# app/contexts/shop/repositories/order.py
# app/contexts/shop/services/order.py
# app/contexts/shop/__init__.py          — context public API, auto-updated
# app/routers/order.py                   — imports from app.contexts.shop
# tests/unit/shop/test_order_service.py  — base cases pre-written
# tests/integration/shop/test_order_router.py — security cases included
# tests/factories/order_factory.py       — factory-boy ready
```

Pre-commit blocks commits if a resource exists without its corresponding test.
CI fails if coverage drops below 80%.

---

## Planned features

### 🤖 AI as a first-class citizen

```python
from calango.agents import AgentRouter

router = AgentRouter(prefix="/agents")

@router.agent("/support", streaming=True, guardrails=True)
async def support_agent():
    """Support agent with access to real account data."""

@router.tool(permissions=["orders:read"])
async def get_orders(context: AgentContext) -> list[OrderOutput]:
    """Tool always scoped to the authenticated user — no BOLA by design."""
    return await OrderRepository.list_by_user(user_id=context.user_id)

@router.tool(requires_approval=True)
async def request_refund(context: AgentContext, order_id: str, reason: str):
    """Human-in-the-loop: pauses, notifies, waits for human approval."""
```

**Default engine: [Agno](https://agno.com)** — ~2µs per agent, 23+ LLM providers, native MCP.

### 🔒 OWASP security by design

```python
# Secure by default — all endpoints require auth
@router.get("/orders")
async def list_orders(current_user: User = Depends(get_current_user)):
    ...

# Explicit public exception — visible in the code
@router.get("/status")
@public
async def health_check():
    ...
```

- **OWASP Top 10:2025** — A01 through A10 addressed in framework design
- **OWASP API Security:2023** — BOLA, mass assignment, rate limiting by default
- **OWASP LLM:2025** — prompt injection, excessive agency, unbounded consumption
- **Security test cases generated** — every resource gets 401, 403, and BOLA tests by default

**Static security gate — ships today.** The framework and every generated project
run a free, OSS, three-layer scan that blocks the build on known issues:

```bash
calango check:security      # SCA (pip-audit) + SAST (Opengrep) — also a CI gate
```

| Layer | Tool | Catches |
|---|---|---|
| SAST inline | Ruff `S` (flake8-bandit) | insecure patterns as you lint |
| SAST deep | Opengrep | dataflow + Calango's own `CL0xx` rules (raw SQL, PII in logs) |
| SCA | pip-audit (PyPA) | known CVEs in dependencies |

All three run *as tools*, never imported into your app — so no copyleft touches
your code. (An in-app runtime firewall is intentionally left as an opt-in: the
mature options are AGPL/NonCommercial.)

### ⚡ Proactive performance detection

```bash
# During development:
X-Calango-Query-Count: 47
X-Calango-N1-Warning: OrderRepository (43 similar queries) ← automatic warning

# Automatic index suggestion:
calango db suggest-indexes

  #1 HIGH PRIORITY: orders.status — 847 queries/day, 97% reduction estimated
  Generate migration? [Y/n]
```

---

## Stack

| Layer | Technology | Why |
|---|---|---|
| **HTTP** | FastAPI | Async-native, automatic OpenAPI, industry standard |
| **Validation** | Pydantic v2 | Performance, strong typing, foundation of everything |
| **ORM** | SQLAlchemy 2 async | Async-native, clean repository pattern |
| **Migrations** | Alembic | Auto-generation, reversible |
| **Cache/Queue** | Redis + ARQ | Async-native, lightweight |
| **Packages** | UV | Fastest resolver, workspace, lockfile |
| **Lint** | Ruff | Replaces flake8 + isort + black |
| **Types** | TY | Modern, integrated with Ruff ecosystem |
| **AI Agents** | Agno | FastAPI-native, MCP, 23+ providers |
| **Infra** | Docker + Compose | Dev identical to CI |

---

## Plugins

### Core SaaS
| Plugin | What it does |
|---|---|
| `calango-identity` | JWT RS256, refresh rotation, OAuth2, RBAC, Teams, invites |
| `calango-multitenancy` | Row-level (Postgres RLS default), schema-level, db-level |
| `calango-payments` | Stripe + MercadoPago/Pix, webhooks with signature verification |
| `calango-plans` | `@plan_limit` decorator, per-plan feature gates |

### Productivity
| Plugin | What it does |
|---|---|
| `calango-search` | PG FTS (default), Typesense, Meilisearch — same interface |
| `calango-notifications` | Email, push, SMS, Slack, outbound webhook, in-app inbox |
| `calango-admin` | SQLAdmin + Admin Copilot (NL2SQL via agent) |
| `calango-media` | S3/GCS/MinIO upload, async conversions (WebP, AVIF, thumbnails) |
| `calango-background` | ARQ (default), Celery, automatic DLQ, retry with backoff |

### AI and Agents
| Plugin | What it does |
|---|---|
| `calango-agents` | Agno engine, AgentRouter, Tool Registry, MCP Server |
| `calango-knowledge` | Knowledge Base with pgvector, RAG over application data |
| `calango-guardrails` | PII filter, moderation, prompt injection detection |
| `calango-cost-control` | Token budget per user/tenant/plan |
| `calango-evals` | deepeval + ragas in CI, response quality gate |

### Model mixins
| Plugin | What it does |
|---|---|
| `soft-delete` | `deleted_at`, automatic query scoping, restore |
| `audit-log` | Change history via SQLAlchemy event listeners |
| `sluggable` | Unique slug with redirect history (friendly_id style) |
| `sortable` | Managed `position` field, atomic reordering |
| `nested-tree` | Closure table or Postgres LTREE, no N+1 |
| `taggable` | Polymorphic tags with namespaces |

### Resilience
| Plugin | What it does |
|---|---|
| `calango-idempotency` | `Idempotency-Key` middleware, essential for payments |
| `calango-health` | `/health` with pluggable checks, Kubernetes format |
| `calango-rate-limit` | `@throttle("100/hour")`, sliding window Redis |
| `calango-feature-flags` | Per-user/group/% rollout flags, Redis or PG backend |

---

## Generated project structure

```
my-project/
├── app/
│   ├── contexts/               # Domain contexts (Phoenix-style)
│   │   └── shop/               # One context per domain boundary
│   │       ├── __init__.py     # Public API — import from here only
│   │       ├── models/         # SQLAlchemy — structure, no business logic
│   │       ├── schemas/        # Pydantic — Input, Output, Update
│   │       ├── repositories/   # Database access — queries only
│   │       └── services/       # Business logic — only here
│   ├── routers/                # HTTP layer — validation and delegation
│   └── agents/                 # Agents and tools (if plugin active)
├── tests/
│   ├── unit/shop/              # Service tests per context
│   ├── integration/shop/       # Router tests with real database
│   └── factories/              # factory-boy
├── CLAUDE.md                   # Context for Claude Code — auto-maintained
├── compose.yml                 # postgres + redis + minio + ollama
├── Dockerfile                  # dev → ci → production
└── .github/workflows/          # CI (6 gates) + CD (staging → prod)
```

---

## Comparison

|  | Calango | FastAPI alone | Django | Flask |
|---|---|---|---|---|
| Convention over Config | ✅ | ❌ | ✅ | ❌ |
| Async-native | ✅ | ✅ | Partial | Partial |
| TDD as default path | ✅ | ❌ | Partial | ❌ |
| AI-assisted ready | ✅ | ❌ | ❌ | ❌ |
| AI agents built-in | ✅ | ❌ | ❌ | ❌ |
| MCP Server | ✅ | ❌ | ❌ | ❌ |
| Full scaffold | ✅ | ❌ | Partial | ❌ |
| CI/CD generated | ✅ | ❌ | ❌ | ❌ |
| OWASP by design | ✅ | ❌ | Partial | ❌ |
| Automatic index hints | ✅ | ❌ | ❌ | ❌ |

---

## Roadmap

| Milestone | What it delivers | Status |
|---|---|---|
| **M1** "calango new works" | Core + CLI scaffold | 🟢 Done |
| **M2** "generate resource" | Full CRUD scaffold with real database | 🟡 In progress |
| **M3** "minimal SaaS" | JWT auth + RBAC + protected endpoints | 🟡 In progress |
| **M4** "SaaS core" | Multi-tenancy (RLS) + payments (Stripe + Pix) | 🔴 Planned |
| **M5** "AI layer" | `calango generate agent` → running agent with MCP | 🔴 Planned |
| **M6** "Ecosystem" | All plugins + published MkDocs docs | 🔴 Planned |

See [ROADMAP.md](ROADMAP.md) for the full breakdown.

### Component status

| Component | Status |
|---|---|
| `calango-core` — exceptions, settings, types | ✅ Done (21 tests) |
| `calango-core` — app factory, middleware, handlers | ✅ Done (10 tests) |
| `calango-cli` — `calango new` | ✅ Done |
| `calango-cli` — `calango generate resource` | ✅ Done (scaffold; no DB layer yet) |
| `calango-cli` — `calango check:security` (SAST + SCA) | ✅ Done |
| `calango-core` — `BaseRepository` + `BaseService` | ✅ Done |
| `calango-cli` — `calango db migrate` | 🟡 Next |
| `calango-identity` — JWT RS256, RBAC, rate limit | 🟡 Mostly done (refresh rotation pending) |
| `calango-agents` | 🔴 Planned |
| `calango-payments` | 🔴 Planned |
| Documentation | 🔴 Planned |

---

## Contributing

Calango is in early stages. If you want to contribute:

1. Read `CLAUDE.md` — it's the full project briefing
2. Read `ROADMAP.md` — phased implementation plan
3. Open an issue before starting any large PR
4. Follow project conventions (Conventional Commits, CoC architecture)

```bash
git clone https://github.com/calango-framework/calango
cd calango
uv sync
uv run pytest packages/
```

---

## License

[PolyForm NonCommercial 1.0.0](LICENSE) — fork and modify freely with attribution, no commercial use.

---

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/calango-mark-white-transparent-1024.png">
  <img src="docs/assets/calango-mark-green-transparent-1024.png" alt="Calango" width="40">
</picture>

Made with ☕ in Brazil

</div>
