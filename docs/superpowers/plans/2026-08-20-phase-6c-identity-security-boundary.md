# Phase 6C Identity Security Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Identity onto supported guards and lifecycle APIs while making Redis failures and token responses safe.

**Architecture:** Identity installs one endpoint-aware Calango request guard, injects the app database dependency, and owns only resources it creates. Router helpers translate refresh and limiter storage failures to a uniform 503 and attach non-cache headers.

**Tech Stack:** FastAPI Users, SlowAPI, Redis asyncio, SQLAlchemy, Pytest/fakeredis.

**Spec:** `docs/superpowers/specs/2026-08-20-phase-6-technical-debt-remediation-design.md`

## Global Constraints

- Existing opaque refresh rotation and family-revocation semantics do not change.
- Authentication endpoints and `@public` endpoints are anonymous; all other HTTP routes and mounts require an active user.
- Redis failures expose only `503 Authentication service unavailable`.
- Successful login and refresh return `Cache-Control: no-store` and `Pragma: no-cache`.

---

### Task 1: Settings validation and proxy policy

**Files:**
- Modify: `packages/calango-plugins/calango-identity/calango_identity/settings.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/rate_limit.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_settings.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_rate_limit.py`

**Interfaces:**
- Produces: positive validated durations/limits, nonblank prefix, parsed RSA keys, `TRUSTED_PROXIES: tuple[str, ...]`.

- [ ] **Step 1: Add failing validation and proxy tests**

```python
@pytest.mark.parametrize("field", ["ACCESS_TOKEN_EXPIRE_MINUTES", "REFRESH_TOKEN_EXPIRE_DAYS", "RATE_LIMIT_LOGIN_PER_MINUTE", "RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL"])
def test_positive_settings(field, valid_keys):
    with pytest.raises(ValidationError):
        IdentitySettings(**valid_keys, **{field: 0})

def test_forwarded_for_ignored_without_trusted_proxy(request):
    request.headers.__dict__["_list"].append((b"x-forwarded-for", b"203.0.113.4"))
    assert resolve_client_ip(request, ()) == request.client.host
```

- [ ] **Step 2: Prove RED, implement validators, prove GREEN, commit**

Use `Field(gt=0)`, a whitespace-rejecting validator, `cryptography.serialization.load_pem_private_key/load_pem_public_key`, and `ipaddress.ip_address/network` for explicit proxy trust.

Run: `uv run pytest packages/calango-plugins/calango-identity/tests/test_settings.py packages/calango-plugins/calango-identity/tests/test_rate_limit.py -v`
Expected: PASS.

```bash
git add packages/calango-plugins/calango-identity/calango_identity/settings.py packages/calango-plugins/calango-identity/calango_identity/rate_limit.py packages/calango-plugins/calango-identity/tests
git commit -m "fix(identity): validate security configuration"
```

### Task 2: Supported authentication guard and owned lifecycle

**Files:**
- Modify: `packages/calango-plugins/calango-identity/calango_identity/dependencies.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/plugin.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_dependencies.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_plugin.py`

**Interfaces:**
- Consumes: `Calango.add_request_guard`, `Calango.database.session`, and private-by-default mounts.
- Produces: `make_authentication_guard(optional_current_user)` without route mutation.

- [ ] **Step 1: Replace mutation-oriented tests with boundary regressions**

```python
def test_private_mount_requires_auth(identity_app):
    child = FastAPI()
    @child.get("/")
    async def root(): return {"ok": True}
    identity_app.mount("/child", child)
    assert TestClient(identity_app).get("/child/").status_code == 401

def test_public_route_before_and_after_plugin_is_anonymous(identity_app):
    @identity_app.get("/health")
    @public
    async def health(): return {"ok": True}
    assert TestClient(identity_app).get("/health").status_code == 200

def test_injected_resources_are_not_closed(identity_app, injected_store):
    with TestClient(identity_app): pass
    assert injected_store.close_calls == 0

def test_owned_redis_clients_close_once(identity_app, owned_redis):
    with TestClient(identity_app): pass
    assert owned_redis.aclose.await_count == 1

def test_permission_boundary(identity_client, token_without_permission, token_with_permission):
    assert identity_client.get("/admin").status_code == 401
    denied = identity_client.get("/admin", headers=bearer(token_without_permission))
    allowed = identity_client.get("/admin", headers=bearer(token_with_permission))
    assert denied.status_code == 403
    assert allowed.status_code == 200
```

- [ ] **Step 2: Prove RED**

Run: `uv run pytest packages/calango-plugins/calango-identity/tests/test_dependencies.py packages/calango-plugins/calango-identity/tests/test_plugin.py -v`
Expected: mount bypass and private FastAPI mutation assertions expose the old design.

- [ ] **Step 3: Install guard and lifecycle through Calango**

Delete `enforce_authentication`. Build a guard that skips endpoints carrying `__calango_public__` and Identity router endpoints carrying `__calango_identity_public__`; otherwise resolve the optional FastAPI Users dependency and raise `AuthenticationError` when absent. Require `Calango` in `register`, use `app.database.session`, register resource cleanup in the framework lifecycle, and distinguish injected versus constructed limiter/Redis/store ownership.

- [ ] **Step 4: Prove GREEN and commit**

Run: `uv run pytest packages/calango-plugins/calango-identity/tests/test_dependencies.py packages/calango-plugins/calango-identity/tests/test_plugin.py -v`
Expected: PASS without imports from `fastapi.dependencies.utils`.

```bash
git add packages/calango-plugins/calango-identity/calango_identity packages/calango-plugins/calango-identity/tests
git commit -m "fix(identity): enforce supported auth boundaries"
```

### Task 3: Redis outage translation and no-store responses

**Files:**
- Modify: `packages/calango-plugins/calango-identity/calango_identity/rate_limit.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/router.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_auth_router.py`
- Modify: `packages/calango-plugins/calango-identity/tests/test_rate_limit.py`
- Create: `packages/calango-plugins/calango-identity/tests/integration/test_redis_outage.py`

**Interfaces:**
- Produces: `set_no_store(response) -> None`; uniform limiter and refresh-store error translation.

- [ ] **Step 1: Add failing response and outage tests**

```python
@pytest.mark.parametrize("path", ["/auth/login", "/auth/refresh"])
def test_token_response_is_not_cacheable(client, path, payload):
    response = client.post(path, data=payload) if path.endswith("login") else client.post(path, json=payload)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"

def test_login_limiter_redis_outage_is_503(client_with_dead_redis):
    response = client_with_dead_redis.post("/auth/login", data={"username": "a@b.test", "password": "x"})
    assert response.status_code == 503
    assert response.json()["message"] == "Authentication service unavailable"
```

- [ ] **Step 2: Prove RED, implement, and prove GREEN**

Set headers on the injected `Response` before returning login/refresh. Wrap limits storage exceptions at the plugin boundary and raise `ServiceUnavailableError` without including the original exception text; retain structured exception logging with secrets filtered.

Run: `uv run pytest packages/calango-plugins/calango-identity/tests/test_auth_router.py packages/calango-plugins/calango-identity/tests/test_rate_limit.py -v`
Expected: PASS.

Run with Redis: `uv run pytest packages/calango-plugins/calango-identity/tests/integration/test_redis_outage.py -v`
Expected: PASS.

```bash
git add packages/calango-plugins/calango-identity
git commit -m "fix(identity): harden Redis and token responses"
```
