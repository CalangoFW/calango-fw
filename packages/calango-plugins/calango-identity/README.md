# calango-identity

`calango-identity` provides RS256 JWT access tokens, user management, RBAC,
rate-limited login, and rotating refresh tokens for Calango applications.

## Installation and registration

```bash
uv add calango-identity
```

Configure RSA keys and Redis before constructing the plugin. Environment
variables use the `IDENTITY__` prefix:

```dotenv
IDENTITY__PRIVATE_KEY="<RSA private-key PEM; use \\n for newlines>"
IDENTITY__PUBLIC_KEY="<RSA public-key PEM; use \\n for newlines>"
IDENTITY__REDIS_URL=redis://localhost:6379/0
```

Optional settings are `IDENTITY__ACCESS_TOKEN_EXPIRE_MINUTES` (default `15`),
`IDENTITY__REFRESH_TOKEN_EXPIRE_DAYS` (default `7`),
`IDENTITY__REFRESH_TOKEN_KEY_PREFIX`, `IDENTITY__RATE_LIMIT_LOGIN_PER_MINUTE`
(default `5`), and `IDENTITY__RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL` (default
`10`).

```python
from calango import Calango
from calango_identity import IdentityPlugin

app = Calango()
app.include_plugin(IdentityPlugin())
```

Once registered, the plugin requires a valid bearer access token on application
routes already attached to the app and on routes added afterward. The plugin's
login, registration, refresh, logout, and password-reset routes remain available
without an access token because they provide their own authentication boundary.

For tests or a custom persistence implementation, inject a value satisfying the
`RefreshTokenStore` protocol:

```python
from calango_identity import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore

app.include_plugin(IdentityPlugin(refresh_store=InMemoryRefreshTokenStore()))
```

## Endpoints

The plugin registers these routes:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/login` | Authenticate and receive access and refresh tokens. |
| `POST` | `/auth/refresh` | Rotate a refresh token and receive a new token pair. |
| `POST` | `/auth/logout` | Revoke the refresh-token family; returns `204`. |
| `POST` | `/auth/register` | Create a user. |
| `POST` | `/auth/forgot-password` | Start the password-reset flow. |
| `POST` | `/auth/reset-password` | Complete the password-reset flow. |
| `GET`, `PATCH`, `DELETE` | `/users/me` | Read, update, or delete the authenticated user. |
| `GET`, `PATCH`, `DELETE` | `/users/{id}` | User management routes supplied by FastAPI Users. |

`/auth/login` accepts OAuth2 form data, not JSON:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=person@example.com&password=correct-horse-battery-staple'
```

It returns a bearer access token, a refresh token, and the access-token expiry
in seconds:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "refresh_token": "<opaque-refresh-token>",
  "expires_in": 900
}
```

Refresh and logout accept JSON:

```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<opaque-refresh-token>"}'

curl -X POST http://localhost:8000/auth/logout \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<opaque-refresh-token>"}'
```

Registration uses the FastAPI Users user-create payload (at minimum `email` and
`password`). Password-reset routes use the corresponding FastAPI Users request
and reset payloads. Consult the generated OpenAPI document for the exact schema
for your installed FastAPI Users version.

## Refresh-token security

Refresh tokens are opaque random values. The store retains only their SHA-256
digests, never the raw token. Rotation is atomic: a successful refresh consumes
the submitted token and issues its replacement in the same token family.

Each family has an absolute lifetime of seven days by default. Rotating a token
does not extend that deadline. Reusing a consumed token revokes every token in
its family; logout also revokes the entire family. Redis storage errors fail
closed: login, refresh, and logout return an authentication-service error rather
than issuing or accepting a token without persistence.

> Never log, store, or place raw refresh tokens in application analytics. Treat
> them like passwords: keep them only in an appropriate client-side credential
> store and send them only to the refresh or logout endpoint.

## Public routes and permissions

Inject the authenticated user when a handler needs it:

```python
from fastapi import Depends
from calango_identity import User, get_current_user


@router.get("/account")
async def account(user: User = Depends(get_current_user)) -> dict[str, str]:
    return {"user_id": str(user.id)}
```

Use `@public` to mark an intentionally public FastAPI route:

```python
from fastapi import APIRouter
from calango_identity import public

router = APIRouter()


@router.get("/status")
@public
async def status() -> dict[str, str]:
    return {"status": "ok"}
```

Use `require_permission()` as a dependency to require an RBAC permission code:

```python
from fastapi import APIRouter
from calango_identity import User, require_permission

router = APIRouter()


@router.post("/reports")
async def create_report(
    user: User = require_permission("reports:create"),
) -> dict[str, str]:
    return {"created_by": str(user.id)}
```
