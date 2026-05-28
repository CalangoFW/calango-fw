# CLAUDE.md — Calango Framework

> Briefing completo para o Claude Code, Cursor, Copilot e assistentes de IA.
> Leia este documento inteiro antes de escrever qualquer código.

---

## O que é o Calango

**Calango** é um meta-framework Python para desenvolvimento web com Convention over Configuration (CoC) flexível. Pense no Phoenix Framework ou Nest.js, mas Python — com IA como cidadã de primeira classe e TDD como caminho de menor resistência.

O mascote é um lagarto calango 🦎 com óculos de nerd e gravatinha borboleta. Personalidade: esperto, ligeiro, um pouco atrevido — mas sempre prestativo.

**Tagline:** *The fast, friendly Python web framework.*

---

## Stack base — não negocie isso

| Camada | Tecnologia | Versão mínima |
|---|---|---|
| Runtime HTTP | FastAPI | 0.115+ |
| Validação | Pydantic v2 | 2.9+ |
| Configuração | pydantic-settings | 2.6+ |
| ORM (SQL) | SQLAlchemy 2 async | 2.0.36+ |
| ODM (Mongo) | Beanie | última |
| Migrations | Alembic | 1.14+ |
| Cache / Queue | Redis + ARQ | redis 5.2+, arq 0.26+ |
| Gerenciador de pacotes | UV | última |
| Linter / Formatter | Ruff | 0.8+ |
| Type checker | TY | última |
| Containerização | Docker + Compose | última |
| Agentes IA | Agno | 2.6+ |

**Python mínimo: 3.12. Sem exceções.**

---

## Estrutura do monorepo

```
calango/
├── pyproject.toml              # UV workspace root
├── packages/
│   ├── calango-core/           # Framework core
│   │   ├── calango/
│   │   │   ├── __init__.py     # __version__ = "0.1.0"
│   │   │   ├── core/           # App factory, middleware, handlers
│   │   │   ├── config/         # CalangoSettings (pydantic-settings)
│   │   │   ├── types/          # CalangoModel, PaginatedResponse, etc.
│   │   │   ├── exceptions/     # CalangoException hierarchy
│   │   │   ├── repository/     # BaseRepository (SQLAlchemy async)
│   │   │   ├── service/        # BaseService
│   │   │   ├── security/       # Middleware, decorators, headers
│   │   │   ├── performance/    # N+1 detector, event loop watchdog
│   │   │   ├── agents/         # AgentBackend protocol, AgentRouter
│   │   │   └── plugins/        # PluginBase, plugin registry
│   │   └── tests/
│   ├── calango-cli/            # CLI e scaffold
│   │   ├── calango_cli/
│   │   │   ├── main.py         # Entry point — calango command
│   │   │   └── commands/
│   │   │       ├── new.py      # calango new <projeto>
│   │   │       ├── generate.py # calango generate resource <nome>
│   │   │       ├── db.py       # calango db migrate|seed|suggest-indexes
│   │   │       ├── plugin.py   # calango plugin add|remove|list
│   │   │       ├── test.py     # calango test [--watch|--evals|--cov]
│   │   │       └── context.py  # calango context [--check|--show]
│   │   └── tests/
│   └── calango-plugins/        # Plugins oficiais
│       ├── calango-identity/
│       ├── calango-payments/
│       ├── calango-search/
│       ├── calango-agents/
│       ├── calango-admin/
│       ├── calango-multitenancy/
│       └── calango-notifications/
└── docs/                       # Documentação (MkDocs Material)
```

---

## Estrutura de projeto gerado pelo `calango new`

Todo projeto Calango segue esta estrutura — **é um contrato imutável**:

```
meu-projeto/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Calango() app factory
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py           # class Settings(CalangoSettings)
│   ├── models/                 # SQLAlchemy models — SEM lógica de negócio
│   ├── schemas/                # Pydantic schemas — sufixos: Input, Output, Update
│   ├── repositories/           # Única camada que acessa o banco
│   ├── services/               # TODA regra de negócio aqui
│   ├── routers/                # FastAPI routers — apenas validação e delegação
│   ├── agents/                 # AgentRouter e tools (quando plugin agents ativo)
│   └── plugins/                # Config de plugins instalados
├── tests/
│   ├── conftest.py             # Fixtures globais (db, client)
│   ├── unit/                   # Testes de services e schemas
│   ├── integration/            # Testes de routers com httpx async
│   └── factories/              # factory-boy para fixtures
├── alembic/
│   └── versions/
├── CLAUDE.md                   # Este arquivo — auto-mantido pelo calango context
├── CLAUDE.local.md             # Contexto específico do projeto — NÃO sobrescrito
├── .cursorrules
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── cd.yml
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
├── compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── .gitignore
└── CHANGELOG.md
```

---

## Convenções de código — siga à risca

### Naming

```python
# Models — PascalCase, sem sufixo
class Pedido(Base): ...

# Schemas — PascalCase + sufixo obrigatório
class PedidoInput(CalangoModel): ...
class PedidoOutput(CalangoModel): ...
class PedidoUpdate(CalangoModel): ...

# Repositories — PascalCase + Repository
class PedidoRepository(BaseRepository[Pedido]): ...

# Services — PascalCase + Service
class PedidoService(BaseService[PedidoRepository]): ...

# Routers — snake_case, um arquivo por resource
# app/routers/pedido.py

# Testes — descritivos, explicam a regra de negócio
async def test_pedido_com_desconto_acima_de_100_deve_aplicar_frete_gratis(): ...
```

### Arquitetura em camadas — ordem de dependência

```
routers → services → repositories → models
```

- **Routers**: recebem request, validam schema, delegam ao service, retornam response. Zero lógica.
- **Services**: toda regra de negócio. Não tocam o banco — chamam o repository.
- **Repositories**: única camada que executa queries. Sem lógica de negócio.
- **Models**: definição de estrutura. Sem métodos de negócio.

### O que NUNCA fazer

```python
# ❌ Lógica de negócio no router
@router.post("/pedidos")
async def criar_pedido(data: PedidoInput, db: AsyncSession = Depends(get_db)):
    if data.valor > 1000:  # ERRADO — isso vai no service
        ...

# ❌ Banco no service diretamente
class PedidoService:
    async def criar(self, data: PedidoInput, db: AsyncSession):  # ERRADO
        await db.execute(...)

# ❌ Lógica no model
class Pedido(Base):
    def calcular_desconto(self):  # ERRADO — isso vai no service
        ...

# ❌ SQL raw sem parametrização
await session.execute(f"SELECT * FROM pedidos WHERE id = '{id}'")  # INJEÇÃO SQL

# ❌ Lib síncrona em contexto async
@router.get("/dados")
async def get_dados():
    response = requests.get("https://api.com")  # BLOQUEIA O EVENT LOOP

# ❌ Stack trace em produção
raise HTTPException(detail=str(exc))  # Usa o handler global do Calango

# ❌ Secrets em código
SECRET_KEY = "minha-chave-secreta"  # Use pydantic-settings + env var

# ❌ PII em logs
logger.info(f"Login: {user.email} senha={password}")  # NUNCA
```

### O que SEMPRE fazer

```python
# ✅ Router delega ao service
@router.post("/pedidos")
async def criar_pedido(
    data: PedidoInput,
    current_user: User = Depends(get_current_user),
    service: PedidoService = Depends(get_pedido_service),
) -> PedidoOutput:
    return await service.criar(data, user=current_user)

# ✅ Service usa repository
class PedidoService(BaseService[PedidoRepository]):
    async def criar(self, data: PedidoInput, *, user: User) -> Pedido:
        return await self.repository.create(data, owner_id=user.id)

# ✅ Repository com eager loading explícito
class PedidoRepository(BaseRepository[Pedido]):
    async def get_with_cliente(self, id: UUID) -> Pedido | None:
        result = await self.session.execute(
            select(Pedido)
            .options(selectinload(Pedido.cliente))
            .where(Pedido.id == id)
        )
        return result.scalar_one_or_none()

# ✅ Schema separado por operação
class PedidoInput(CalangoModel):
    valor: Decimal
    cliente_id: UUID

class PedidoOutput(CalangoModel):
    id: UUID
    valor: Decimal
    status: str
    criado_em: datetime
    cliente: ClienteOutput

class PedidoUpdate(CalangoModel):
    status: Literal["confirmado", "cancelado"] | None = None
```

---

## Testes — TDD é o caminho de menor resistência

### Estrutura obrigatória por resource

Para cada `app/services/pedido.py` deve existir `tests/unit/test_pedido_service.py`.
O hook `calango-no-untested-resource` no pre-commit verifica isso.

### Padrão de teste

```python
# tests/unit/test_pedido_service.py
import pytest
from tests.factories.pedido_factory import PedidoFactory

class TestPedidoService:
    """Testes descritivos — cada nome documenta uma regra de negócio."""

    async def test_criar_pedido_com_dados_validos_deve_persistir(self, db):
        ...

    async def test_criar_pedido_sem_cliente_deve_levantar_not_found(self, db):
        ...

    async def test_usuario_nao_acessa_pedido_de_outro_usuario(self, db):
        """BOLA: isolamento por owner_id."""
        ...

# tests/integration/test_pedido_router.py
class TestPedidoRouter:
    async def test_endpoint_exige_autenticacao(self, client):
        response = await client.get("/api/v1/pedidos/qualquer-id")
        assert response.status_code == 401

    async def test_usuario_nao_acessa_pedido_de_outro(self, client, auth_headers):
        """Caso de segurança gerado pelo scaffold — sempre presente."""
        ...
```

### Fixtures padrão (conftest.py gerado)

```python
@pytest.fixture
async def db():
    """Sessão com rollback automático — sem limpeza manual."""
    async with test_db_session() as session:
        yield session

@pytest.fixture
async def client(db):
    """Cliente httpx com banco isolado."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
```

### Coverage

- Threshold: **80% mínimo** — CI falha abaixo disso.
- Gate no CI: `pytest --cov=app --cov-fail-under=80`
- Relatório HTML: `calango test --cov-report=html`

---

## Sistema de plugins

### PluginBase — interface obrigatória

```python
class PluginBase:
    name: str
    version: str
    requires: list[str] = []          # Dependências de outros plugins

    def register(self, app: FastAPI) -> None:
        """Registra routers, middleware e hooks de lifecycle."""
        ...

    def migrations(self) -> list[str]:
        """Retorna paths das migrations do plugin."""
        ...

    def settings(self) -> type[BaseSettings]:
        """Classe de settings do plugin (pydantic-settings)."""
        ...

    def test_fixtures(self) -> list:
        """Fixtures pytest injetadas nos projetos que usam o plugin."""
        ...

    def context_md(self) -> str:
        """Bloco para o CLAUDE.md — descreve o plugin para assistentes de IA."""
        ...
```

### Plugins planejados (implementar nesta ordem)

**Tier 1 — Core SaaS:**
1. `calango-identity` — JWT RS256, refresh rotation, OAuth2, RBAC, Teams
2. `calango-multitenancy` — RLS Postgres (padrão), schema-level, db-level
3. `calango-payments` — Stripe + MercadoPago/Pix, webhooks, idempotência

**Tier 2 — Produtividade:**
4. `calango-search` — PG FTS (padrão), Typesense, Meilisearch
5. `calango-notifications` — email, push, SMS, Slack, webhook outbound
6. `calango-admin` — SQLAdmin + Admin Copilot (NL2SQL)
7. `calango-media` — S3/GCS/MinIO, conversões async (Pillow/ffmpeg)

**Tier 3 — Dados avançados:**
8. `calango-agents` — Agno como engine padrão, AgentRouter, Tool Registry, MCP Server
9. `calango-background` — ARQ (padrão), Celery, dead letter queue

**Tier 4 — Mixins de model:**
10. `soft-delete` — deleted_at, queries automáticas, restore
11. `audit-log` — histórico via SQLAlchemy event listeners
12. `sluggable` — slug único, histórico de redirects
13. `sortable` — campo position gerenciado
14. `nested-tree` — closure table ou LTREE (PG)
15. `taggable` — tags polimórficas com namespaces

**Tier 5 — SaaS avançado:**
16. `calango-plans` — plan_limit decorator, features por plano
17. `calango-feature-flags` — Flipper-style, Redis ou PG backend
18. `calango-teams` — Team com membros, roles, convites

---

## AgentBackend — o contrato de agentes

```python
from typing import Protocol, AsyncIterator, runtime_checkable

@runtime_checkable
class AgentBackend(Protocol):
    async def run(self, prompt: str, context: AgentContext) -> AgentResponse: ...
    async def stream(self, prompt: str, context: AgentContext) -> AsyncIterator[str]: ...
    def register_tool(self, fn: ToolDefinition) -> None: ...
    def list_tools(self) -> list[str]: ...
    async def get_memory(self, session_id: str, user_id: str) -> list[dict]: ...
    async def save_memory(self, session_id: str, user_id: str, messages: list[dict]) -> None: ...
    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
```

**Implementação padrão: Agno v2.6+**
- Performance: ~2µs por agente, 3.75 KiB por sessão
- FastAPI nativo via `AgentOS.get_app()`
- MCP: consome e expõe MCP servers
- 23+ providers de LLM
- Human-in-the-loop nativo
- ReliabilityEval para CI

**AgentContext — injetado automaticamente:**

```python
@dataclass
class AgentContext:
    user_id: str | None
    tenant_id: str | None
    session_id: str
    request_id: str
    ip_address: str
    permissions: list[str]
    plan: str | None
    metadata: dict[str, Any]
```

**Uso:**

```python
from calango.agents import AgentRouter

router = AgentRouter(prefix="/agents")

@router.agent("/suporte", streaming=True, guardrails=True)
async def agente_suporte():
    """Agente de suporte com acesso aos dados da conta."""

@router.tool(permissions=["pedidos:read"])
async def buscar_pedidos(context: AgentContext, status: str | None = None):
    """Tool sempre scoped ao usuário autenticado — sem BOLA por design."""
    return await PedidoRepository.list_by_user(user_id=context.user_id)

@router.tool(requires_approval=True)
async def solicitar_reembolso(context: AgentContext, pedido_id: str, motivo: str):
    """Human-in-the-loop: pausa, notifica, aguarda aprovação."""
    ...
```

---

## Segurança — OWASP por design

### Postura: secure by default, explicit to override

```python
# Todos os endpoints exigem auth por padrão (plugin identity ativo)
@router.get("/pedidos")
async def listar(current_user: User = Depends(get_current_user)):
    ...

# Exceção explícita e visível
@router.get("/status")
@public
async def health():
    ...

# RBAC declarativo
@router.post("/admin/users")
@require_permission("users:admin")
async def criar_usuario_admin(...):
    ...
```

### Checklist de segurança implementado no framework

**OWASP Top 10 Web 2025:**
- A01 Broken Access Control → `@public` explícito, ownership check no repository
- A02 Security Misconfiguration → headers HTTP automáticos, CORS fechado
- A03 Supply Chain → `uv.lock` commitado, `pip-audit` no CI
- A04 Cryptographic Failures → Argon2 para senhas, RS256 para JWT, `secrets` module
- A05 Injection → SQLAlchemy ORM obrigatório, regras Ruff para SQL raw
- A06 Insecure Design → SECURITY.md gerado, reset de senha seguro por padrão
- A07 Authentication Failures → rate limit em `/auth`, JWT expiry curto, refresh rotation
- A08 Data Integrity → assinatura de webhooks obrigatória, idempotência em jobs
- A09 Logging Failures → eventos de segurança logados automaticamente
- A10 Exceptional Conditions → handler global que nunca expõe stack trace em produção

**OWASP API Security 2023:**
- API1 BOLA → repository sempre recebe `current_user`, ownership verificado
- API3 Mass Assignment → schemas separados por operação (Input/Update/Output)
- API4 Resource Consumption → paginação obrigatória, rate limiting padrão

**OWASP LLM 2025:**
- LLM01 Prompt Injection → plugin guardrails, separação system/user prompt
- LLM02 Sensitive Disclosure → filtro PII no output do agente
- LLM06 Excessive Agency → `requires_approval` para ações destrutivas
- LLM10 Unbounded Consumption → budget de tokens via plugin Plans

### Regras Ruff customizadas do Calango

```
CL001: Use 'httpx.AsyncClient' instead of 'requests' in async context
CL002: Use 'aiofiles.open' instead of 'open' in async context
CL003: Blocking call inside coroutine
CL020: HTTP call to dynamic URL — validate against allowlist
CL030: Hardcoded secret detected
CL031: Weak hash algorithm
CL032: 'random' module used for security
CL040: Raw SQL string interpolation
CL050: Potential PII in log statement
CL010: CPU-bound handler — consider background job
```

---

## Performance — o que o framework detecta e previne

### N+1 queries

Em desenvolvimento, header automático em cada response:
```
X-Calango-Query-Count: 47
X-Calango-N1-Warning: PedidoRepository.get_cliente (43 queries similares)
```

Threshold: warning em 5+ queries similares, erro (500) em 20+ (dev apenas).

### Event loop

Watchdog detecta bloqueio > 50ms e loga warning com stack trace.
Regras Ruff detectam chamadas síncronas bloqueantes em funções async.

### Connection pool — defaults saudáveis

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)
```

### Detecção automática de índices ausentes

```bash
calango db suggest-indexes
# Analisa query history, sugere índices com impacto estimado
# Gera migration Alembic automaticamente
```

### Primitivas de concorrência

```python
from calango.concurrency import atomic, advisory_lock
from calango.cache import cached

@atomic
async def confirmar_pagamento(pedido_id: UUID): ...

async with advisory_lock(f"estoque:{produto_id}"): ...

@cached(ttl=300, lock=True)  # Previne cache stampede
async def get_catalogo(): ...
```

---

## CI/CD — gates progressivos

```
quality (lint + types)
    ↓
test-unit (cobertura ≥ 80%)
    ↓
test-integration (postgres + redis reais)
    ↓ ↓ (paralelo)
security          evals (se plugin agents)
    ↓ ↓
build (Docker production stage)
    ↓
deploy-staging (ao merge em main)
    ↓
deploy-production (aprovação manual + tag v*)
```

Falha em qualquer gate bloqueia os seguintes.

---

## Git e práticas ágeis

### Conventional Commits — enforçado pelo hook commit-msg

```
feat(pedidos): adiciona endpoint de cancelamento
fix: corrige cálculo de desconto em parcelas
feat!: altera schema PedidoOutput (BREAKING CHANGE)
```

Tipos: `feat fix docs test chore refactor perf ci build`

### Branch naming — validado pelo hook pre-push

```
feature/*   fix/*   chore/*   release/*   hotfix/*
```

### Definition of Done (PR template)

- Testes escritos e passando (≥ 80% cobertura)
- Sem warnings de N+1 no CI
- `calango check:security` sem findings críticos
- CLAUDE.md atualizado se necessário
- Migrations testadas localmente
- Revisão de pelo menos 1 pessoa

---

## Docker — ambiente idêntico do dev ao CI

### Dockerfile stages

```
base → development (hot reload) → ci (testes) → production (nobody, sem dev deps)
```

### Serviços no compose.yml

Sempre presentes: `app`, `postgres`, `redis`, `minio`
Por plugin: `ollama` (agents), `langfuse` (agent-tracing), `typesense` (search)

---

## Versionamento de API

- URL versioning: `/api/v1/`, `/api/v2/`
- `router_v1.version(2)` herda endpoints e permite override parcial
- Headers automáticos em endpoints deprecados: `Deprecation`, `Sunset`, `Link`
- OpenAPI isolado por versão: `GET /api/v1/openapi.json`

---

## Multi-tenancy (plugin calango-multitenancy)

- **Row-level (padrão):** RLS do Postgres — isolamento no banco, não no código
- **Schema-level:** uma schema por tenant, migrations via Alembic
- **Database-level:** banco separado por tenant (enterprise)

```python
@tenantable  # Adiciona tenant_id + RLS policy automaticamente
class Pedido(Base): ...
```

Resolução: subdomain → JWT claim → header `X-Tenant-ID`

---

## SDK cliente (calango sdk:generate)

```bash
calango sdk:generate --lang=typescript --out=./sdk
```

Gera cliente tipado a partir do OpenAPI. CI falha se SDK commitado diverge da API atual.

---

## Identidade visual

| Token | Hex | Uso |
|---|---|---|
| `calango-green-500` | `#3d8a34` | Primária — CTAs, links |
| `calango-green-400` | `#5cb84f` | Hover |
| `calango-amber-500` | `#c47f17` | Warnings, acento |
| `calango-sand-900` | `#2c2416` | Texto principal |
| `calango-sand-100` | `#f5f0e8` | Background |

Fontes: `JetBrains Mono` (código), `Inter` (interface)

---

## Comandos do CLI

```bash
# Scaffold
calango new <nome> [--db=postgres|mongo] [--ci=github|gitlab|bitbucket] [--agents]

# Geração de código
calango generate resource <nome>     # model + schema + repo + service + router + testes
calango generate model <nome>
calango generate service <nome>
calango generate agent <nome>
calango generate version v2

# Banco de dados
calango db migrate
calango db seed
calango db rollback
calango db suggest-indexes           # Detecta colunas sem índice e gera migration
calango db analyze-indexes           # Detecta índices não utilizados

# Plugins
calango plugin add <nome>
calango plugin remove <nome>
calango plugin list

# Testes
calango test                         # Todos os testes
calango test --watch                 # Re-executa ao salvar
calango test --integration           # Apenas integração
calango test --evals                 # Evals de agentes
calango test --lint-names            # Valida nomes descritivos
calango test --cov-report=html

# Qualidade e segurança
calango check:security [--env=production]
calango check:indexes
calango bench [--compare-baseline]
calango profile GET /api/v1/pedidos

# Contexto IA
calango context                      # Regenera CLAUDE.md e equivalentes
calango context --check              # Verifica se está atualizado (CI)
calango context --show               # Exibe no terminal

# SDK
calango sdk:generate [--lang=typescript|python|kotlin|swift]
calango sdk:check

# Release
calango release                      # Calcula versão, gera CHANGELOG, cria tag
calango commit                       # Assistente interativo de commit

# Setup
calango setup:github                 # Configura labels, protection, environments
calango setup:agile [--tool=linear|jira|github]
```

---

## O que já está implementado

- [x] `calango-core`: `CalangoException` hierarchy (9 tipos)
- [x] `calango-core`: `CalangoSettings` com sub-settings compostos
- [x] `calango-core`: `CalangoModel`, `PaginatedResponse`, `OrderDirection`
- [x] `calango-core`: `Calango(FastAPI)` app factory
- [x] `calango-core`: `CalangoMiddleware` (request_id, headers de segurança, logs)
- [x] `calango-core`: handlers de exceção globais (nunca expõe stack trace em produção)
- [x] `calango-cli`: `calango new` — gera 18 artefatos completos
- [x] 57 testes passando (20 core + 37 CLI)

## O que implementar a seguir (nesta ordem)

1. `BaseRepository[T]` — SQLAlchemy 2 async com session via DI
2. `BaseService[R]` — injeção de repository
3. `calango generate resource` — gera os 8 arquivos do resource com testes
4. `calango db migrate` — wrapper do Alembic
5. `calango-identity` plugin — FastAPI-Users base + JWT RS256 + RBAC
6. `calango-multitenancy` plugin — RLS Postgres
7. `calango-agents` plugin — Agno + AgentRouter + Tool Registry + MCP Server
8. `calango check:security` — auditoria pré-deploy
9. `calango db suggest-indexes` — detecção de índices ausentes
10. `calango-payments` plugin — Stripe + MercadoPago

---

## Referências

- [FastAPI docs](https://fastapi.tiangolo.com)
- [Pydantic v2 docs](https://docs.pydantic.dev/latest/)
- [SQLAlchemy 2 async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Agno docs](https://docs.agno.com)
- [OWASP Top 10:2025](https://owasp.org/www-project-top-ten/)
- [OWASP API Security 2023](https://owasp.org/www-project-api-security/)
- [OWASP LLM Top 10:2025](https://genai.owasp.org)
- [Conventional Commits](https://www.conventionalcommits.org)
- [UV docs](https://docs.astral.sh/uv/)
- [Ruff docs](https://docs.astral.sh/ruff/)
