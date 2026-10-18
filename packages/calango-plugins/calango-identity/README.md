# calango-identity

`calango-identity` provides RS256 JWT access tokens, user management, RBAC,
rate-limited login, and rotating refresh tokens for Calango applications.

## Installation and registration

```bash
uv add calango-identity
```

A new project can start with Identity already wired: `calango new my-api
--identity` generates `app/plugins/identity.py`, includes the plugin in
`app/main.py`, and lists the settings below in `.env.example`.

Configure RSA keys and Redis before constructing the plugin. Settings use the
`IDENTITY__` prefix and are read from the environment or the project's `.env`:

```dotenv
IDENTITY__PRIVATE_KEY="<RSA private-key PEM; use \\n for newlines>"
IDENTITY__PUBLIC_KEY="<RSA public-key PEM; use \\n for newlines>"
IDENTITY__REDIS_URL=redis://localhost:6379/0
```

Optional settings are `IDENTITY__ACCESS_TOKEN_EXPIRE_MINUTES` (default `15`),
`IDENTITY__REFRESH_TOKEN_EXPIRE_DAYS` (default `7`),
`IDENTITY__REFRESH_TOKEN_KEY_PREFIX`, `IDENTITY__RATE_LIMIT_LOGIN_PER_MINUTE`
(default `5`), and `IDENTITY__RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL` (default
`10`). Durations and limits must be positive and the RSA keys must parse;
invalid settings fail at startup without echoing secret values.

The per-IP login limit uses the connecting peer address. Behind a reverse proxy,
trust `X-Forwarded-For` only from explicit proxy addresses or networks:

```dotenv
IDENTITY__TRUSTED_PROXIES='["10.0.0.0/8", "192.0.2.10"]'
```

```python
from calango import Calango
from calango_identity import IdentityPlugin

from app.core.config import Settings

app = Calango(settings=Settings())
app.include_plugin(IdentityPlugin())
```

Once registered, every HTTP route and mounted application requires a valid
bearer access token — including routes and routers added after the plugin. Mark
intentional exceptions with `@public` (see below) or `app.mount(path, sub_app,
public=True)`. The plugin's login, registration, refresh and logout routes (and
the reset and verification routes, when enabled) provide their own
authentication boundary and stay available without an access token.

## Database tables

Identity ships an Alembic migration for its five tables (`identity_users`,
`identity_roles`, `identity_permissions`, `identity_user_roles`,
`identity_role_permissions`). `calango db migrate` discovers installed plugin
migrations and applies them with the project's own revisions.

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
| `POST` | `/auth/forgot-password` | Start the password-reset flow (when enabled). |
| `POST` | `/auth/reset-password` | Complete the password-reset flow (when enabled). |
| `POST` | `/auth/request-verify-token` | Send an e-mail verification token (when enabled). |
| `POST` | `/auth/verify` | Verify an e-mail address (when enabled). |
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
its family; logout also revokes the entire family.

Successful login and refresh responses carry `Cache-Control: no-store` and
`Pragma: no-cache` so no cache keeps the issued tokens.

Redis failures fail closed. Whether the refresh-token store or the login rate
limiter loses Redis, login, refresh and logout return the same `503`
envelope — `{"error": "service_unavailable", "message": "Authentication service
unavailable"}` — rather than issuing or accepting a token without persistence.
The response never includes storage details, and the operational log records
only the exception type.

> Never log, store, or place raw refresh tokens in application analytics. Treat
> them like passwords: keep them only in an appropriate client-side credential
> store and send them only to the refresh or logout endpoint.

## Account events, password reset and verification

Identity decides *when* an account event happens; your application decides how
it is delivered. Implement the async `IdentityEvents` protocol and inject it:

```python
from calango_identity import IdentityEvents, IdentityPlugin, User


class EmailDelivery(IdentityEvents):
    async def on_registered(self, user: User, request) -> None: ...

    async def on_login(self, user: User, request, response) -> None: ...

    async def send_password_reset(self, user: User, token: str, request) -> None:
        ...  # e-mail a link carrying the token

    async def send_verification(self, user: User, token: str, request) -> None:
        ...  # e-mail a verification link


app.include_plugin(
    IdentityPlugin(
        events=EmailDelivery(),
        enable_password_reset=True,
        enable_verification=True,
    )
)
```

- Reset and verification endpoints are off by default; enable them explicitly.
- With `CALANGO_ENV=production`, enabling them without a provider fails at
  startup, and so does passing `LoggingIdentityEvents`.
- Outside production the default provider is `LoggingIdentityEvents`, which
  logs only the event name and user id — never e-mail addresses or tokens — so
  it cannot complete a reset.
- A provider failure is logged by exception type and never changes the HTTP
  response: `/auth/forgot-password` answers the same `202` for known accounts,
  unknown e-mails and failed deliveries. Retries are the provider's job.
- Reset and verification tokens are signed with secrets derived from the
  Identity signing key, one per purpose.

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

On a `@public` route, `get_current_user` returns the user when the request
carries a valid token and `None` when it is anonymous, so one handler can serve
both:

```python
@router.get("/feed")
@public
async def feed(user: User | None = Depends(get_current_user)) -> dict[str, bool]:
    return {"personalized": user is not None}
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

`require_permission()` returns `401` when the request is anonymous (also on a
`@public` route) and `403` when the user lacks the permission.

## Testing authenticated routes

Override `get_current_user` to run a test as a fixed user without issuing
tokens. The override also satisfies the authentication guard, and clearing
`app.dependency_overrides` restores normal enforcement:

```python
app.dependency_overrides[get_current_user] = lambda: test_user
```

## WebSocket endpoints

Identity's authentication guard covers HTTP routes and mounts only. WebSocket
endpoints are **not** authenticated by the plugin: a WebSocket route accepts
anonymous connections unless the endpoint verifies credentials itself (for
example, by validating a token sent in the first message before accepting any
other traffic).
