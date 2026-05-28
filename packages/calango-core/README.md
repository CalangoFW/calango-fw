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

Settings are loaded from environment variables or a `.env` file:

```bash
APP_NAME="My API"
SECURITY__SECRET_KEY="your-key"
DATABASE__URL="postgresql+asyncpg://user:pass@localhost/db"
DATABASE__POOL_SIZE=20
REDIS__URL="redis://localhost:6379/0"
```

```python
# Or constructed directly for testing
settings = CalangoSettings(
    APP_NAME="Test API",
    security=SecuritySettings(SECRET_KEY="test-key"),
)
```

## Development

```bash
uv sync
uv run pytest packages/calango-core/tests/ -v --cov=calango
```

**54 tests · 97% coverage**
