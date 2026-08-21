# Phase 6 Technical Debt Remediation — Design Spec

> Status: Approved for planning
> Scope: Calango core, CLI scaffold, plugin contract, and calango-identity

## Objective

Make Phase 6 operationally complete: a generated Calango application can install
Identity, migrate its database, register and recover users, authenticate every HTTP
boundary by default, rotate sessions through Redis, and shut down cleanly. The work
fixes verified defects and technical debt only; Phase 7 multitenancy is out of scope.

## Completion flow

The release-level acceptance path is:

```text
calango new
  → install/configure Identity
  → alembic upgrade head
  → register
  → login
  → access private/public/RBAC routes
  → refresh
  → logout
  → password-reset event delivery
```

Every step must work with PostgreSQL and Redis services, not only SQLite or fake
implementations.

## Package and database architecture

### Runtime dependencies

`calango-identity` declares `calango-core` and `calango-plugin-base` as package
dependencies because it imports both contracts during normal operation. Workspace
source mappings remain development-only and published metadata must install every
runtime dependency.

### Canonical metadata

Identity's `User`, `Role`, and `Permission` models inherit the canonical
`calango.db.Base`. The private Identity `DeclarativeBase` is removed. Application
and plugin tables therefore share one SQLAlchemy metadata graph without merging
metadata objects at runtime.

Identity table names remain:

- `identity_users`
- `identity_roles`
- `identity_permissions`
- `identity_user_roles`
- `identity_role_permissions`

### Plugin migrations

The plugin contract exposes migration locations through an immutable typed
descriptor rather than an import string that may not exist. Its public shape is
`PluginMigration(name: str, versions: Traversable, depends_on: tuple[str, ...])`:
`name` is the unique plugin identifier, `versions` is an importlib-resources
location that also works from an installed wheel, and `depends_on` contains plugin
identifiers whose revisions must precede it. Duplicate names, missing dependencies
and dependency cycles fail before Alembic runs.

`calango-identity` ships a real Alembic revision that creates all five tables,
indexes and foreign keys, and can downgrade them in reverse dependency order.
Generated Alembic configuration discovers installed plugin descriptors and adds
their version locations. Autogenerate imports plugin models before reading
`calango.db.Base.metadata`.

The Identity migration is tested against PostgreSQL with both upgrade and
downgrade. SQLite metadata tests remain fast unit coverage, not migration evidence.

### Engine lifecycle

`calango.core.database` owns an explicit database runtime object containing the
async engine and session factory. It supports:

- construction from `CalangoSettings`;
- `start()` or equivalent idempotent initialization;
- per-request `AsyncSession` dependencies;
- idempotent async disposal;
- injection of a custom session dependency for tests and advanced applications.

`Calango` integrates this runtime through its lifespan without replacing a
user-provided lifespan. Framework startup and user startup compose in a documented
order; shutdown runs in reverse order. The CLI scaffold generates the same supported
pattern. There is no module-global engine that survives application shutdown.

## Authentication boundary

### Public extension point

Authentication-by-default must not mutate `APIRoute.dependant`, lazy-router cache
versions, or other private FastAPI fields. `Calango` exposes a public framework
extension for adding a global request guard before application routes are finalized.
Identity installs its guard through that extension.

The guard has three outcomes:

- Identity-owned authentication endpoints use their own boundary and remain public.
- Application endpoints marked with `@public` allow anonymous access.
- Every other HTTP endpoint requires an active bearer-token user.

Routes declared before or after plugin registration and routes included through an
`APIRouter` have identical behavior.

### Mounted applications

Mounted HTTP applications are authentication boundaries, not implicit exceptions.
Identity protects mounts by default through an authenticated mount wrapper. An
application must opt out explicitly with the public-mount API; merely mounting a
subapplication never makes it anonymous.

The wrapper preserves the mounted application's lifespan, root path, streaming and
exception behavior. WebSocket authentication is not silently implied by the HTTP
wrapper: if WebSocket support is not implemented in this scope, its exclusion is
explicitly documented and tested.

### RBAC

`require_permission("resource:action")` resolves the current user through the same
public guard contract. It returns `401` without authentication, `403` without the
permission, and the user on success. Role and permission collections are loaded
without request-time lazy-loading surprises.

## Redis, limits, and session responses

Identity has one Redis configuration but two owned clients: the async refresh store
and SlowAPI/limits storage. Ownership is explicit. Plugin-owned resources close on
shutdown; injected resources remain open.

Redis connection or command failures in either the refresh store or login limiter
produce the same non-sensitive `503 Authentication service unavailable` envelope.
No storage traceback, username, password, token, token digest, or Redis URL enters
the HTTP response.

Both configured login limits remain active:

- `RATE_LIMIT_LOGIN_PER_MINUTE` per resolved client IP;
- `RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL` per normalized email.

Proxy-aware IP resolution is configurable; trusting forwarding headers is opt-in
and requires an explicit trusted-proxy policy.

Successful login and refresh responses include:

```http
Cache-Control: no-store
Pragma: no-cache
```

The existing opaque refresh-token rotation, absolute family expiration, digest-only
storage, atomic reuse detection, and family revocation contracts remain unchanged.

## Configuration

Top-level Calango environment settings use the `CALANGO_` namespace:

- `CALANGO_APP_NAME`
- `CALANGO_VERSION`
- `CALANGO_ENV`
- `CALANGO_DEBUG`

Nested database, Redis and security namespaces retain their documented prefixes.
For one deprecation cycle, legacy unprefixed top-level names are read only when the
corresponding `CALANGO_` value is absent. A deprecation warning identifies the exact
legacy name without exposing its value. Tests set explicit environments and do not
delete host variables globally through an autouse fixture.

Identity settings validate:

- access-token minutes greater than zero;
- refresh-token days greater than zero;
- both rate limits greater than zero;
- non-empty refresh key prefix;
- syntactically valid RSA PEM keys at startup.

Configuration failures are startup errors, never delayed until the first login.

## Identity events and password recovery

### Event protocol

`IdentityEvents` is an async protocol injected into `IdentityPlugin`. It defines
focused callbacks for:

- `on_registered(user, request)`;
- `on_login(user, request, response)`;
- `send_password_reset(user, token, request)`;
- `send_verification(user, token, request)`.

The protocol contains business events only; it does not prescribe SMTP, Resend or
another delivery provider.

### Production and development behavior

Password-reset and verification endpoints are enabled only when an event provider
capable of delivering their tokens is configured. `IdentityPlugin` receives the
top-level `CalangoSettings` during installation and uses its validated `ENV` value
to select production behavior; it does not independently infer an environment.
Production startup fails clearly if delivery endpoints are enabled without such a
provider.

`LoggingIdentityEvents` is development-only. It may log event type and opaque user
identifier, but never email addresses, passwords, access tokens, refresh tokens,
reset tokens, verification tokens, private keys or token digests.

### Privacy and failures

Forgot-password responses remain indistinguishable for existing and nonexistent
emails. Once a syntactically valid request is accepted, the endpoint always returns
the same `202` envelope, including when a provider reports a delivery failure.
Provider errors are recorded through redacted structured operational logging; token
and account existence never appear in the response. Retry ownership belongs to the
injected provider, preventing the Identity plugin from inventing provider-specific
semantics.

## Error handling

- Missing database initialization is detected at startup, before accepting traffic.
- Missing or inconsistent migration descriptors fail migration commands with the
  plugin name and safe remediation guidance.
- Redis failures use `503`; invalid credentials and tokens use uniform `401`.
- Authorization failures use `403` without enumerating the user's other permissions.
- Configuration errors identify the invalid setting name, not secret values.
- Event-provider failures never reveal whether an account exists.

## Testing strategy

### Unit tests

- package metadata declares all imported runtime packages;
- settings namespace, legacy fallback and positive-value validation;
- event protocol dispatch and redaction;
- public/private/RBAC guards;
- Redis error translation and token-response cache headers;
- engine startup/disposal ownership.

Every behavioral correction follows RED → GREEN → refactor, and its failing test is
captured before production changes.

### Integration tests

Using real PostgreSQL and Redis services:

- Identity migration upgrade and downgrade;
- registration and duplicate registration;
- login and both limits;
- private, public, RBAC and mounted routes;
- refresh rotation, concurrent use, reuse-family revocation and logout;
- Redis outage behavior;
- password-reset event delivery and provider failure;
- application and plugin resource shutdown.

### End-to-end scaffold test

Generate a project in a temporary directory, enable Identity, configure service
containers, apply Alembic migrations, start the app, and exercise register → login →
private/public → refresh → logout. The generated project must pass its tests and
static gates.

### Repository gates

Before Phase 6 is marked complete:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run ty check packages/`
- full Pytest suite in normal and hostile host environments;
- SCA and SAST security gate;
- PostgreSQL/Redis integration suite;
- generated-project end-to-end test.

The README test badge and roadmap counts are derived from verified output rather
than maintained as unrelated constants.

## Documentation and compatibility

The Identity README documents:

- package installation and database lifecycle;
- plugin migration application;
- event-provider injection;
- protected and public mounts;
- Redis failure behavior;
- token no-store headers;
- the one-cycle environment-variable migration.

The roadmap returns Phase 6 to complete only after every completion gate passes.
No Phase 7 API, tenant model or RLS behavior is introduced by this remediation.
