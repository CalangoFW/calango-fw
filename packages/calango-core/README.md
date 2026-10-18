# calango-core

Core package for the [Calango Framework](../../README.md).

## What's inside

| Module | What it provides |
|---|---|
| `calango.core.app` | `Calango(FastAPI)` — app factory with middleware and handlers pre-wired |
| `calango.core.middleware` | `CalangoMiddleware` — request ID, security headers, version header |
| `calango.core.handlers` | Global exception handlers — structured JSON, no stack trace leaks |
| `calango.config` | `CalangoSettings` with composable sub-settings (database, redis, security) |
| `calango.exceptions` | 9-type exception hierarchy mapping to HTTP status codes |
| `calango.types` | `CalangoModel`, `PaginatedResponse[T]`, `OrderDirection` |

## Quick start

```python
from calango import Calango, CalangoSettings
from calango.config import SecuritySettings
from calango.exceptions import NotFoundError
from calango import CalangoModel, PaginatedResponse

settings = CalangoSettings(
    APP_NAME="My API",
    security=SecuritySettings(SECRET_KEY="your-secret-key"),
)
app = Calango(settings=settings)


class ProductOutput(CalangoModel):
    id: int
    name: str
    price: float


@app.get("/products/{id}")
def get_product(id: int) -> ProductOutput:
    if id != 1:
        raise NotFoundError("Product not found")
    return ProductOutput(id=1, name="T-Shirt", price=49.90)


@app.get("/products")
def list_products() -> PaginatedResponse[ProductOutput]:
    items = [ProductOutput(id=1, name="T-Shirt", price=49.90)]
    return PaginatedResponse(items=items, total=1, page=1, page_size=10)
```

Every response automatically gets:

```
x-request-id: <uuid>          — unique per request, included in error responses
x-calango-version: 0.1.0-dev
x-content-type-options: nosniff
x-frame-options: DENY
strict-transport-security: max-age=31536000; includeSubDomains
referrer-policy: strict-origin-when-cross-origin
```

## Exceptions

All exceptions produce consistent JSON with `error`, `message`, and `request_id`:

```python
raise NotFoundError("Product not found")
# HTTP 404 → {"error": "not_found", "message": "Product not found", "request_id": "..."}

raise AuthorizationError("Permission denied")
# HTTP 403

raise ConflictError("Email already registered")
# HTTP 409

raise RateLimitError("Too many requests", retry_after=60)
# HTTP 429
```

Unhandled exceptions always return 500 with no internal details exposed.

## Configuration

Settings are loaded from environment variables or a `.env` file. Top-level
settings use the `CALANGO_` namespace; nested settings keep their prefixes:

```bash
CALANGO_APP_NAME="My API"
CALANGO_ENV=production          # development | production | test
CALANGO_DEBUG=false
SECURITY__SECRET_KEY="your-key"
DATABASE__URL="postgresql+asyncpg://user:pass@localhost/db"
DATABASE__POOL_SIZE=20
REDIS__URL="redis://localhost:6379/0"
```

The unprefixed names `APP_NAME`, `VERSION`, `ENV` and `DEBUG` still work for one
release cycle, only when the `CALANGO_` variable is absent, and emit a
`DeprecationWarning` naming the variable to rename (never its value).

```python
# Or constructed directly for testing
settings = CalangoSettings(
    APP_NAME="Test API",
    security=SecuritySettings(SECRET_KEY="test-key"),
)
```

## Database lifecycle

`Calango` owns its database: `app.database` creates the async engine when the
application starts and disposes it on shutdown. Framework startup runs first,
then plugin lifespans, then your own `lifespan`; shutdown runs in reverse.
Request handlers get a session from `calango.core.database.get_db`:

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from calango.core.database import get_db


@app.get("/orders")
async def list_orders(session: AsyncSession = Depends(get_db)): ...
```

Tests can point every session, including the ones plugins use, at a test
session by overriding both entry points:

```python
for dependency in (get_db, app.database.session):
    app.dependency_overrides[dependency] = test_session
```

## Request guards and mounts

Plugins add application-wide guards with `app.add_request_guard()` or
`app.add_dependency_request_guard()`. Guards cover every HTTP boundary — API
routes, Starlette routes and mounted applications, including routers included
or extended after the guard was registered. Mounts are guarded by default; make
an intentionally public mount explicit:

```python
app.mount("/static", static_files, public=True)
```

WebSocket connections are not guarded; WebSocket endpoints must authenticate
themselves.

## Development

```bash
uv sync
uv run pytest packages/calango-core/tests/ -v --cov=calango
```

**133 tests**
