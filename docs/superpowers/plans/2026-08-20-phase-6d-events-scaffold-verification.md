# Phase 6D Events, Scaffold, and Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver password recovery through an injected event contract and prove the generated Identity application end to end.

**Architecture:** `UserManager` forwards business callbacks to an async `IdentityEvents` provider. The generated app uses the supported runtime/migration pattern; service-backed integration and scaffold tests are the final completion gate.

**Tech Stack:** FastAPI Users, Protocol typing, Calango CLI/Jinja, PostgreSQL, Redis, Pytest, Ruff, Ty, pip-audit, Opengrep.

**Spec:** `docs/superpowers/specs/2026-08-20-phase-6-technical-debt-remediation-design.md`

## Global Constraints

- Accepted forgot-password requests always return the same `202`, including provider failure.
- Logs never contain email, password, access/refresh/reset/verification token, digest, or private key.
- Production uses `CalangoSettings.ENV`; enabled delivery endpoints require a capable provider.
- Phase 7 tenant and RLS behavior is excluded.

---

### Task 1: Async Identity event provider

**Files:**
- Create: `packages/calango-plugins/calango-identity/calango_identity/events.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/manager.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/plugin.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/router.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/__init__.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_events.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_auth_router.py`

**Interfaces:**
- Produces: async `IdentityEvents` protocol with `on_registered`, `on_login`, `send_password_reset`, `send_verification`; development-only `LoggingIdentityEvents`.

- [ ] **Step 1: Add failing dispatch, privacy, and startup tests**

```python
async def test_manager_delivers_reset_token(events, user, request):
    manager = make_manager(events)
    await manager.on_after_forgot_password(user, "opaque-reset", request)
    assert events.reset_calls == [(user.id, "opaque-reset")]

def test_production_rejects_enabled_delivery_without_provider(prod_app):
    with pytest.raises(RuntimeError, match="IdentityEvents"):
        prod_app.include_plugin(IdentityPlugin(enable_password_reset=True))

def test_provider_failure_still_returns_uniform_202(client, failing_events):
    response = client.post("/auth/forgot-password", json={"email": "known@example.test"})
    unknown = client.post("/auth/forgot-password", json={"email": "missing@example.test"})
    assert response.status_code == unknown.status_code == 202
    assert response.json() == unknown.json()
```

- [ ] **Step 2: Prove RED**

Run: `uv run pytest packages/calango-plugins/calango-identity/tests/test_events.py packages/calango-plugins/calango-identity/tests/test_auth_router.py -v`
Expected: missing protocol and discarded reset token.

- [ ] **Step 3: Implement provider forwarding and redaction**

Define the four protocol methods with `Request | None`, pass the provider into `make_get_user_manager`, forward manager hooks, and catch provider delivery exceptions outside the account-existence branch so the route returns the same accepted envelope. `LoggingIdentityEvents` logs only event name and `str(user.id)`. Use `app.settings.ENV == "production"`; enable reset/verification routers only with explicit flags and validate provider capability during registration.

- [ ] **Step 4: Prove GREEN and commit**

Run: `uv run pytest packages/calango-plugins/calango-identity/tests/test_events.py packages/calango-plugins/calango-identity/tests/test_auth_router.py -v`
Expected: PASS and `caplog.text` contains none of the supplied secrets.

```bash
git add packages/calango-plugins/calango-identity
git commit -m "feat(identity): deliver account lifecycle events"
```

### Task 2: Supported generated application

**Files:**
- Modify: `packages/calango-cli/calango_cli/templates/app/main.py.jinja`
- Modify: `packages/calango-cli/calango_cli/templates/app/core/config.py.jinja`
- Modify: `packages/calango-cli/calango_cli/templates/env.example.jinja`
- Modify: `packages/calango-cli/calango_cli/templates/pyproject.toml.jinja`
- Modify: `packages/calango-cli/tests/test_new_command.py`
- Modify: `packages/calango-cli/README.md`

**Interfaces:**
- Consumes: Calango-owned DB lifecycle, plugin migrations, and `IdentityPlugin(events=...)`.
- Produces: generated project that starts without manual `configure_engine()`.

- [ ] **Step 1: Add a failing generated-project contract test**

```python
def test_generated_main_uses_supported_lifecycle(tmp_path, runner):
    result = runner.invoke(app, ["new", "sample", "--path", str(tmp_path)])
    assert result.exit_code == 0
    main = (tmp_path / "sample/app/main.py").read_text()
    assert "configure_engine" not in main
    assert "Calango(settings=settings)" in main
```

Also assert `.env.example` contains `CALANGO_ENV`/`CALANGO_DEBUG` and project dependencies include selected Identity runtime packages.

- [ ] **Step 2: Prove RED, update templates, prove GREEN, commit**

Run: `uv run pytest packages/calango-cli/tests/test_new_command.py -v`
Expected before template updates: missing new environment/runtime contract; afterward: PASS.

```bash
git add packages/calango-cli
git commit -m "fix(cli): generate operational Identity applications"
```

### Task 3: Service-backed integration and scaffold E2E

**Files:**
- Create: `packages/calango-plugins/calango-identity/tests/integration/conftest.py`
- Create: `packages/calango-plugins/calango-identity/tests/integration/test_identity_flow.py`
- Create: `packages/calango-cli/tests/e2e/test_generated_identity.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: marker `integration`; fixtures `postgres_url` and `redis_url` supplied by explicit CI/local environment variables.

- [ ] **Step 1: Write complete service flow tests**

```python
async def test_identity_lifecycle(real_client, delivered_events):
    registered = await real_client.post("/auth/register", json=USER)
    assert registered.status_code == 201
    login = await real_client.post("/auth/login", data=LOGIN)
    assert login.status_code == 200
    tokens = login.json()
    assert (await real_client.get("/private", headers=bearer(tokens))).status_code == 200
    rotated = await real_client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    assert (await real_client.post("/auth/logout", json={"refresh_token": rotated.json()["refresh_token"]})).status_code == 204
```

Add assertions for duplicate registration, public/RBAC/mounted routes, two login limits, concurrent reuse-family revocation, Redis outage, reset delivery, provider failure, and shutdown counters. The E2E test invokes `calango new`, configures the two service URLs, runs `alembic upgrade head`, starts the ASGI app, and repeats register → login → private/public → refresh → logout.

- [ ] **Step 2: Prove RED, add fixtures/harness, and prove GREEN**

Run: `uv run pytest -m integration packages/calango-plugins/calango-identity/tests/integration packages/calango-cli/tests/e2e -v`
Expected initially: fixture/harness failures; after wiring real services and generated-project subprocess isolation: PASS.

- [ ] **Step 3: Commit the executable acceptance gate**

```bash
git add pyproject.toml packages/calango-plugins/calango-identity/tests/integration packages/calango-cli/tests/e2e
git commit -m "test(identity): verify generated flow with services"
```

### Task 4: Documentation and final repository gates

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `packages/calango-core/README.md`
- Modify: `packages/calango-plugins/calango-identity/README.md`

**Interfaces:**
- Consumes: verified commands and behavior from Tasks 1–3.
- Produces: accurate setup, lifecycle, migrations, events, mounts, Redis, headers, environment migration, and Phase 6 status documentation.

- [ ] **Step 1: Update documentation from verified behavior**

Document exact imports and commands: construct `Calango(settings=Settings())`, inject `IdentityEvents`, run `calango db migrate`, mark public endpoints/mounts, configure trusted proxies, and migrate legacy variables to `CALANGO_`. Record HTTP 503/no-store behavior and explicit WebSocket exclusion.

- [ ] **Step 2: Run all release gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check packages/
DEBUG=release uv run pytest -v
uv run pytest -m integration -v
uv run pip-audit
uv run opengrep scan --config security/opengrep/calango.yml .
```

Expected: every command exits 0; test count used in README/ROADMAP equals the final Pytest collection. If a gate fails, return to the task that owns the behavior and add its regression test before changing production code.

- [ ] **Step 3: Mark Phase 6 complete and commit**

```bash
git add README.md ROADMAP.md packages/calango-core/README.md packages/calango-plugins/calango-identity/README.md
git commit -m "docs: close verified Phase 6 remediation"
```
