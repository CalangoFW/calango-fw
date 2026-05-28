<div align="center">

```
  ╔═══════════════════════════════╗
  ║   🦎  C A L A N G O           ║
  ║   The fast, friendly          ║
  ║   Python web framework        ║
  ╚═══════════════════════════════╝
```

[![Python](https://img.shields.io/badge/python-3.12+-4a9e3f?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-4a9e3f?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-5cb84f?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/status-em%20desenvolvimento-c47f17?style=flat-square)]()

*Convention over Configuration. TDD como padrão. IA como cidadã de primeira classe.*

</div>

---

## O que é o Calango?

Calango é um meta-framework Python para desenvolvimento web inspirado no **Phoenix Framework** e no **Nest.js** — com a alma do **Rails** e o coração do **FastAPI**.

A ideia é simples: você não deveria gastar energia decidindo onde colocar cada arquivo, como configurar o CI, ou como estruturar seus testes. O Calango decide isso por você — e quando precisar sair da convenção, a saída é explícita e documentada.

```bash
pip install calango
calango new meu-projeto
cd meu-projeto && docker compose up
```

Em menos de dois minutos você tem um projeto com banco, cache, storage, CI/CD, CLAUDE.md para seus assistentes de IA, e testes prontos para escrever.

> *Corre não, corre sim — mas com testes!* 🦎

---

## Por que o Calango?

### Para o desenvolvedor Python de 2025

Python dominou IA e ML. FastAPI dominou APIs. Mas nenhum framework Python trata **desenvolvimento assistido por IA** como princípio de design — nem faz **TDD o caminho de menor resistência**.

O Calango foi desenhado do zero para o desenvolvedor que usa Claude Code, Cursor, Codex ou Antigravity no dia a dia:

- **Estrutura previsível como contrato** — qualquer IA abre o projeto e sabe onde está cada coisa
- **`CLAUDE.md` gerado e mantido automaticamente** — contexto sempre atualizado para seus assistentes
- **Testes gerados junto com o código** — não como etapa separada
- **Agentes IA como primitiva do framework** — não como plugin de terceiro grau

### Convention over Configuration — mas flexível

```bash
# Caminho feliz: zero configuração
calango generate resource Pedido
# Cria: model + schema + repository + service + router + testes + factory

# Precisa sair da convenção? É explícito:
# Crie em outro lugar — o framework não te impede,
# apenas não te guia automaticamente.
```

### Baterias incluídas, não forçadas

Você ativa o que precisa, quando precisa:

```bash
calango plugin add identity      # JWT, OAuth2, RBAC
calango plugin add payments      # Stripe, Pix, webhooks
calango plugin add agents        # Agentes IA com Agno
calango plugin add multitenancy  # RLS no Postgres
calango plugin add search        # FTS, Typesense, Meilisearch
```

---

## Funcionalidades principais

### 🏗️ Scaffold completo em um comando

```bash
calango new minha-api --db=postgres --ci=github --agents

# Gera em ~45 segundos:
# ✓ Estrutura de diretórios CoC
# ✓ Dockerfile multi-stage (dev/ci/production)
# ✓ Docker Compose com postgres, redis, minio, ollama
# ✓ GitHub Actions CI (6 gates progressivos) + CD
# ✓ PR template com Definition of Done
# ✓ Issue templates
# ✓ CLAUDE.md para Claude Code, .cursorrules para Cursor
# ✓ Git inicializado com Conventional Commits enforçado
# ✓ pyproject.toml com cobertura de 80% como gate
# ✓ SECURITY.md e PERFORMANCE.md
```

### 🧪 TDD como caminho de menor resistência

```bash
calango generate resource Pedido

# Cria junto com o código:
# tests/unit/test_pedido_service.py    — casos base já escritos
# tests/integration/test_pedido_router.py — casos de segurança incluídos
# tests/factories/pedido_factory.py    — factory-boy pronto
```

O pre-commit bloqueia commit se existe resource sem teste correspondente.
O CI falha se cobertura < 80%.

### 🤖 IA como cidadã de primeira classe

```python
from calango.agents import AgentRouter

router = AgentRouter(prefix="/agents")

@router.agent("/suporte", streaming=True, guardrails=True)
async def agente_suporte():
    """Agente de suporte com acesso aos dados reais da conta."""

@router.tool(permissions=["pedidos:read"])
async def buscar_pedidos(context: AgentContext) -> list[PedidoOutput]:
    """Tool sempre scoped ao usuário — sem BOLA por design."""
    return await PedidoRepository.list_by_user(user_id=context.user_id)

@router.tool(requires_approval=True)
async def solicitar_reembolso(context: AgentContext, pedido_id: str, motivo: str):
    """Human-in-the-loop: pausa, notifica, aguarda aprovação humana."""
    ...
```

**Engine padrão: [Agno](https://agno.com)** — ~2µs por agente, 23+ providers de LLM, MCP nativo.  
**Em desenvolvimento:** Ollama local no Docker Compose. **Em produção:** Anthropic, OpenAI, Gemini — uma variável de ambiente.

### 🔒 Segurança OWASP por design

```python
# Secure by default — todos os endpoints exigem auth
@router.get("/pedidos")
async def listar(current_user: User = Depends(get_current_user)):
    ...

# Exceção explícita e visível no código
@router.get("/status")
@public
async def health_check():
    ...
```

- **OWASP Top 10:2025** — A01 a A10 tratados no design do framework
- **OWASP API Security:2023** — BOLA, mass assignment, rate limiting por padrão
- **OWASP LLM:2025** — prompt injection, excessive agency, unbounded consumption
- **`calango check:security`** — auditoria pré-deploy com score e findings acionáveis
- **Casos de segurança gerados** — todo resource tem testes 401, 403 e BOLA por padrão

### ⚡ Performance com detecção proativa

```bash
# Durante desenvolvimento:
X-Calango-Query-Count: 47
X-Calango-N1-Warning: PedidoRepository (43 queries similares) ← aviso automático

# Sugestão automática de índices:
calango db suggest-indexes

  #1 ALTA PRIORIDADE: pedidos.status — 847 queries/dia, redução de 97%
  Gerar migration? [S/n]
```

- **Watchdog de event loop** — detecta código bloqueante em corrotinas
- **Regras Ruff customizadas** — detectam `requests` dentro de `async def` em lint time
- **Benchmark no CI** — regressão de performance bloqueia o PR

---

## Stack

| | Tecnologia | Por quê |
|---|---|---|
| **HTTP** | FastAPI | Async nativo, OpenAPI automático, padrão de mercado |
| **Validação** | Pydantic v2 | Performance, tipagem forte, base de tudo |
| **ORM** | SQLAlchemy 2 async | Async nativo, padrão repository limpo |
| **Migrations** | Alembic | Auto-geração, reversível |
| **Cache/Queue** | Redis + ARQ | Async nativo, leve |
| **Pacotes** | UV | O mais rápido, workspace, lockfile |
| **Lint** | Ruff | Substitui flake8 + isort + black |
| **Types** | TY | Moderno, integrado ao ecossistema Ruff |
| **Agentes** | Agno | FastAPI nativo, MCP, 23+ providers |
| **Infra** | Docker + Compose | Dev idêntico ao CI |

---

## Plugins disponíveis

### Core SaaS
| Plugin | O que faz |
|---|---|
| `calango-identity` | JWT RS256, refresh rotation, OAuth2 social, RBAC, Teams, convites |
| `calango-multitenancy` | Row-level (RLS PG padrão), schema-level, db-level |
| `calango-payments` | Stripe + MercadoPago/Pix, webhooks com verificação de assinatura |
| `calango-plans` | `@plan_limit` decorator, features por plano |

### Produtividade
| Plugin | O que faz |
|---|---|
| `calango-search` | PG FTS (padrão), Typesense, Meilisearch — mesma interface |
| `calango-notifications` | Email, push, SMS, Slack, webhook outbound, inbox in-app |
| `calango-admin` | SQLAdmin + Admin Copilot (NL2SQL via agente) |
| `calango-media` | Upload S3/GCS/MinIO, conversões async (WebP, AVIF, thumbs) |
| `calango-background` | ARQ (padrão), Celery, DLQ automática, retry com backoff |

### IA e Agentes
| Plugin | O que faz |
|---|---|
| `calango-agents` | Agno engine, AgentRouter, Tool Registry, MCP Server |
| `calango-knowledge` | Knowledge Base com pgvector, RAG sobre dados da aplicação |
| `calango-guardrails` | Filtro PII, moderação, detecção de prompt injection |
| `calango-cost-control` | Budget de tokens por usuário/tenant/plano |
| `calango-evals` | deepeval + ragas no CI, gate de qualidade de respostas |

### Mixins de model (inspirados no Rails/Laravel)
| Plugin | O que faz |
|---|---|
| `soft-delete` | `deleted_at`, queries automáticas, restore |
| `audit-log` | Histórico de mudanças via SQLAlchemy event listeners |
| `sluggable` | Slug único com histórico de redirects (friendly_id style) |
| `sortable` | Campo `position` gerenciado, reordenação atômica |
| `nested-tree` | Closure table ou LTREE do Postgres, sem N+1 |
| `taggable` | Tags polimórficas com namespaces |

### Resiliência
| Plugin | O que faz |
|---|---|
| `calango-idempotency` | Middleware `Idempotency-Key`, essencial para pagamentos |
| `calango-health` | `/health` com checks plugáveis, formato Kubernetes |
| `calango-rate-limit` | `@throttle("100/hour")`, sliding window Redis |
| `calango-feature-flags` | Flag por usuário/grupo/% rollout, backend Redis ou PG |

---

## Quick start

### Pré-requisitos

- Python 3.12+
- Docker e Docker Compose
- UV (`pip install uv`)

### Criar um projeto

```bash
# Instalar o Calango
pip install calango

# Criar projeto
calango new minha-api

# Entrar no diretório e configurar
cd minha-api
cp .env.example .env
# Edite .env com suas configurações

# Subir o ambiente
docker compose up

# Em outro terminal: aplicar migrations e rodar testes
calango db migrate
calango test
```

### Gerar seu primeiro resource

```bash
calango generate resource Produto

# Criado automaticamente:
# app/models/produto.py
# app/schemas/produto.py        (ProdutoInput, ProdutoOutput, ProdutoUpdate)
# app/repositories/produto.py
# app/services/produto.py
# app/routers/produto.py
# tests/unit/test_produto_service.py      (casos base)
# tests/integration/test_produto_router.py (casos de segurança)
# tests/factories/produto_factory.py
```

### Adicionar autenticação

```bash
calango plugin add identity

# Registrado automaticamente:
# POST /api/v1/auth/login
# POST /api/v1/auth/refresh
# POST /api/v1/auth/register
# POST /api/v1/auth/forgot-password
# Todos os endpoints protegidos por padrão
```

### Adicionar um agente de IA

```bash
calango plugin add agents
calango generate agent Suporte

# Cria:
# app/agents/suporte_agent.py
# tests/agents/test_suporte_agent.py
# MCP Server em /mcp — conecte seu Claude Code
```

---

## Comparação

|  | Calango | FastAPI puro | Django | Flask |
|---|---|---|---|---|
| CoC | ✅ | ❌ | ✅ | ❌ |
| Async nativo | ✅ | ✅ | Parcial | Parcial |
| TDD como padrão | ✅ | ❌ | Parcial | ❌ |
| AI-assisted ready | ✅ | ❌ | ❌ | ❌ |
| Agentes IA | ✅ | ❌ | ❌ | ❌ |
| MCP Server | ✅ | ❌ | ❌ | ❌ |
| Scaffold completo | ✅ | ❌ | Parcial | ❌ |
| CI/CD gerado | ✅ | ❌ | ❌ | ❌ |
| OWASP por design | ✅ | ❌ | Parcial | ❌ |
| Índices automáticos | ✅ | ❌ | ❌ | ❌ |

---

## Estrutura de projeto

```
minha-api/
├── app/
│   ├── models/         # SQLAlchemy — estrutura, sem lógica
│   ├── schemas/        # Pydantic — Input, Output, Update
│   ├── repositories/   # Acesso ao banco — só queries
│   ├── services/       # Regras de negócio — só aqui
│   ├── routers/        # HTTP — validação e delegação
│   └── agents/         # Agentes e tools (se plugin ativo)
├── tests/
│   ├── unit/           # Services e schemas — sem banco
│   ├── integration/    # Routers com banco real
│   └── factories/      # factory-boy
├── CLAUDE.md           # Contexto para Claude Code — auto-mantido
├── compose.yml         # postgres + redis + minio + ollama
├── Dockerfile          # dev → ci → production
└── .github/workflows/  # CI (6 gates) + CD (staging → prod)
```

---

## Identidade

O **Calango** (*Ameiva ameiva*) é o lagarto mais ágil do sertão brasileiro. Rápido, esperto, difícil de pegar — e sempre com os olhos abertos para o que vem pela frente.

Cores: verde-lagarto `#3d8a34` · âmbar-sol `#c47f17` · terra-sertão `#2c2416`

---

## Status do projeto

🚧 **Em desenvolvimento ativo** — versão 0.1.0

| Componente | Status |
|---|---|
| `calango-core` | 🟡 Em desenvolvimento |
| `calango-cli` (new) | 🟡 Em desenvolvimento |
| `calango-cli` (generate) | 🔴 Planejado |
| `calango-identity` | 🔴 Planejado |
| `calango-agents` | 🔴 Planejado |
| `calango-payments` | 🔴 Planejado |
| Documentação | 🔴 Planejada |

---

## Contribuindo

O Calango está nos estágios iniciais. Se você quer contribuir:

1. Leia o `CLAUDE.md` — é o briefing completo do projeto
2. Leia o `docs/spec.md` — especificação detalhada de cada componente
3. Abra uma issue antes de começar qualquer PR grande
4. Siga as convenções do projeto (Conventional Commits, CoC)

```bash
git clone https://github.com/calango-framework/calango
cd calango
uv sync
calango test
```

---

## Licença

MIT © Calango Contributors

---

<div align="center">

**Feito com 🦎 e ☕ no Brasil**

*Corre não, corre sim — mas com testes!*

</div>
