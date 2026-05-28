# calango-cli

CLI and scaffold for the [Calango Framework](../../README.md).

> **In development.** The `calango new` command is the next milestone.

## Planned commands

### Project scaffold

```bash
calango new my-api
calango new my-api --db=postgres --ci=github --agents
```

Generates a fully wired project: Dockerfile, Docker Compose, GitHub Actions CI/CD,
`CLAUDE.md`, `.cursorrules`, Conventional Commits hooks, and 80% coverage gate —
all ready to `docker compose up`.

### Code generation

```bash
calango generate resource Order
# Creates: model + schema + repository + service + router + tests + factory

calango generate agent Support
# Creates: AgentRouter + tools + eval tests + MCP endpoint
```

### Database

```bash
calango db migrate          # uv run alembic upgrade head
calango db seed             # runs app/seeds/ in order
calango db rollback         # uv run alembic downgrade -1
calango db suggest-indexes  # analyzes query history, generates migration
```

### Quality and security

```bash
calango test                    # all tests
calango test --watch            # re-run on save
calango test --cov-report=html  # coverage report
calango check:security          # pre-deploy OWASP audit
```

### Context maintenance

```bash
calango context         # regenerate CLAUDE.md and .cursorrules
calango context --check # verify context is up to date (CI)
```

## Development

```bash
uv sync
uv run pytest packages/calango-cli/tests/ -v
```
