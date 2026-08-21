# Phase 6A Core Runtime and Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Calango an owned async database lifecycle, collision-safe settings, and supported request-guard/mount APIs.

**Architecture:** `Calango` composes framework and user lifespans and owns a `DatabaseRuntime`. Authentication plugins register guards through public Calango APIs; a dispatching guard evaluates endpoints and mounts without mutating FastAPI internals.

**Tech Stack:** Python 3.12, FastAPI/Starlette, SQLAlchemy asyncio, Pydantic Settings, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-phase-6-technical-debt-remediation-design.md`

## Global Constraints

- Top-level settings use `CALANGO_`; legacy names work for exactly one deprecation cycle and emit value-free warnings.
- Framework startup precedes user startup; shutdown occurs in reverse order.
- No module-global engine and no mutation of private FastAPI route fields.
- HTTP mounts are private unless explicitly marked public; WebSockets remain explicitly outside this phase.

---

### Task 1: Namespaced top-level configuration

**Files:**
- Modify: `packages/calango-core/calango/config/__init__.py`
- Modify: `packages/calango-core/tests/test_config.py`
- Modify: `conftest.py`

**Interfaces:**
- Produces: `CalangoSettings` reading `CALANGO_APP_NAME`, `CALANGO_VERSION`, `CALANGO_ENV`, and `CALANGO_DEBUG`, with legacy fallback.

- [ ] **Step 1: Add failing namespace and hostile-host tests**

```python
def test_calango_prefix_wins(monkeypatch):
    monkeypatch.setenv("DEBUG", "release")
    monkeypatch.setenv("CALANGO_DEBUG", "true")
    value = CalangoSettings(security=SecuritySettings(SECRET_KEY="test"))
    assert value.DEBUG is True

def test_legacy_name_warns_without_value(monkeypatch):
    monkeypatch.delenv("CALANGO_APP_NAME", raising=False)
    monkeypatch.setenv("APP_NAME", "legacy-secret-like-value")
    with pytest.warns(DeprecationWarning, match="APP_NAME") as records:
        value = CalangoSettings(security=SecuritySettings(SECRET_KEY="test"))
    assert value.APP_NAME == "legacy-secret-like-value"
    assert "legacy-secret-like-value" not in str(records[0].message)
```

- [ ] **Step 2: Prove RED**

Run: `uv run pytest packages/calango-core/tests/test_config.py -v`
Expected: hostile `DEBUG` parsing fails and `CALANGO_` precedence is absent.

- [ ] **Step 3: Implement prefixed sources and remove global env deletion**

Use `SettingsConfigDict(env_prefix="CALANGO_", env_file=".env", env_nested_delimiter="__", extra="ignore")`; add a custom settings source that copies only absent legacy top-level keys and calls `warnings.warn(f"{name} is deprecated; use CALANGO_{name}", DeprecationWarning)`. Delete the autouse fixture in root `conftest.py` that removes host variables; tests must use `monkeypatch` locally.

- [ ] **Step 4: Prove GREEN and commit**

Run: `DEBUG=release uv run pytest packages/calango-core/tests/test_config.py packages/calango-core/tests/test_app.py -v`
Expected: PASS.

```bash
git add conftest.py packages/calango-core/calango/config/__init__.py packages/calango-core/tests/test_config.py
git commit -m "fix(core): namespace application settings"
```

### Task 2: Owned database runtime and composed lifespan

**Files:**
- Modify: `packages/calango-core/calango/core/database.py`
- Modify: `packages/calango-core/calango/core/app.py`
- Modify: `packages/calango-core/calango/__init__.py`
- Modify: `packages/calango-core/tests/test_db.py`
- Modify: `packages/calango-core/tests/test_app.py`

**Interfaces:**
- Produces: `DatabaseRuntime(settings, session_dependency=None)`, `start()`, `session()`, `close()`, and `Calango.database`.

- [ ] **Step 1: Add failing ownership and ordering tests**

```python
async def test_runtime_start_and_close_are_idempotent(settings):
    runtime = DatabaseRuntime(settings)
    await runtime.start(); first = runtime.engine
    await runtime.start(); assert runtime.engine is first
    await runtime.close(); await runtime.close()
    assert runtime.engine is None

def test_framework_and_user_lifespan_order(settings):
    events = []
    @asynccontextmanager
    async def lifespan(app):
        events.append("user-start"); yield; events.append("user-stop")
    app = Calango(settings=settings, lifespan=lifespan)
    with TestClient(app):
        assert app.database.started
        events.append("request")
    assert events == ["user-start", "request", "user-stop"]
    assert not app.database.started
```

- [ ] **Step 2: Prove RED**

Run: `uv run pytest packages/calango-core/tests/test_db.py packages/calango-core/tests/test_app.py -v`
Expected: `DatabaseRuntime` and `app.database` do not exist.

- [ ] **Step 3: Implement the runtime and lifespan composition**

```python
class DatabaseRuntime:
    def __init__(self, settings: CalangoSettings, session_dependency: Callable | None = None):
        self.settings = settings
        self._session_dependency = session_dependency
        self.engine = None
        self._maker = None

    async def start(self) -> None:
        if self.engine is None:
            self.engine = create_async_engine(self.settings.database.URL, pool_pre_ping=True)
            self._maker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        if self._session_dependency is not None:
            async for session in self._session_dependency():
                yield session
            return
        if self._maker is None:
            raise RuntimeError("Database runtime is not started")
        async with self._maker() as session:
            yield session

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
        self.engine = None
        self._maker = None
```

Store engine and maker on the instance, raise `RuntimeError("Database runtime is not started")` before yielding, dispose idempotently, and make `Calango` enter framework resources before the supplied lifespan and close them after it exits. Keep `get_db(request: Request)` as the stable FastAPI dependency delegating to `request.app.database.session()`.

- [ ] **Step 4: Prove GREEN and commit**

Run: `uv run pytest packages/calango-core/tests/test_db.py packages/calango-core/tests/test_app.py -v`
Expected: PASS, including disposal after startup exceptions.

```bash
git add packages/calango-core/calango packages/calango-core/tests/test_db.py packages/calango-core/tests/test_app.py
git commit -m "feat(core): own database lifecycle"
```

### Task 3: Public HTTP guard and mount contract

**Files:**
- Create: `packages/calango-core/calango/core/guards.py`
- Modify: `packages/calango-core/calango/core/app.py`
- Modify: `packages/calango-core/calango/core/__init__.py`
- Create: `packages/calango-core/tests/test_guards.py`

**Interfaces:**
- Produces: `RequestGuard = Callable[[Request], Awaitable[None]]`, `Calango.add_request_guard(guard)`, `Calango.mount(path, app, *, public=False, ...)`.

- [ ] **Step 1: Add failing route and mount tests**

```python
async def deny(_request):
    raise AuthenticationError("Authentication required")

def test_guard_covers_routes_added_before_and_after_registration(app):
    @app.get("/before")
    async def before(): return {"ok": True}
    app.add_request_guard(deny)
    @app.get("/after")
    async def after(): return {"ok": True}
    client = TestClient(app)
    assert client.get("/before").status_code == 401
    assert client.get("/after").status_code == 401

def test_mount_is_guarded_by_default(app):
    child = FastAPI()
    @child.get("/")
    async def root(): return {"ok": True}
    app.add_request_guard(deny)
    app.mount("/child", child)
    assert TestClient(app).get("/child/").status_code == 401

def test_public_mount_skips_guard(app):
    child = FastAPI()
    @child.get("/")
    async def root(): return {"ok": True}
    app.add_request_guard(deny)
    app.mount("/docs-app", child, public=True)
    assert TestClient(app).get("/docs-app/").status_code == 200

def test_websocket_scope_is_not_guarded(app):
    app.add_request_guard(deny)
    @app.websocket("/ws")
    async def websocket(socket):
        await socket.accept(); await socket.send_text("ok"); await socket.close()
    with TestClient(app).websocket_connect("/ws") as socket:
        assert socket.receive_text() == "ok"
```

Each test installs a guard that raises `AuthenticationError`, asserts HTTP `401`, and records that the selected endpoint is available through `request.scope["endpoint"]`.

- [ ] **Step 2: Prove RED**

Run: `uv run pytest packages/calango-core/tests/test_guards.py -v`
Expected: APIs are missing and mounts bypass the guard.

- [ ] **Step 3: Implement one public dispatch layer**

Create a Starlette middleware/route wrapper that calls guards only for `scope["type"] == "http"`; record public mount prefixes at registration and skip them. `add_request_guard` appends to an ordered app-owned tuple and rejects registration after startup. Do not access `APIRoute.dependant` or `_effective_*` fields.

- [ ] **Step 4: Prove GREEN and commit**

Run: `uv run pytest packages/calango-core/tests/test_guards.py packages/calango-core/tests/test_app.py -v`
Expected: PASS.

```bash
git add packages/calango-core/calango/core packages/calango-core/tests/test_guards.py
git commit -m "feat(core): add supported request guard boundary"
```
