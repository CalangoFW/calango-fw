# Phase 7 Multitenancy (Row-Level Security) — Design Spec

> Status: Approved for planning
> Scope: new `calango-multitenancy` plugin, Calango core guard composition,
> plugin migration contract, CLI scaffold and generator

## Objective

Let a Calango application serve many tenants from one PostgreSQL database while
the database itself guarantees isolation: a tenant member reads and writes only
their tenant's rows, even when application code forgets to filter or issues raw
SQL. Isolation is transparent to repositories and services.

## Scope

In scope: the row-level strategy (PostgreSQL RLS), which is the default
strategy in `CLAUDE.md`.

Out of scope, each a later phase of its own: schema-per-tenant and
database-per-tenant strategies, subdomain and JWT-claim tenant resolution as
built-ins, tenant deletion, invitations and custom tenant roles (the future
`calango-teams` plugin), and the `AgentContext`/plans integrations (those
plugins do not exist yet).

## Decisions

| Topic | Decision | Rejected |
|---|---|---|
| User ↔ tenant | Global users; membership table; one user may belong to many tenants | one tenant per user; tenants without users |
| Tenant selection | `X-Tenant-ID` header (UUID or slug) plus a pluggable `TenantResolver` | built-in subdomain; spec's subdomain → JWT → header chain |
| Database role | One non-superuser role for app and migrations; `FORCE ROW LEVEL SECURITY`; startup refuses roles that bypass RLS | owner + runtime role pair; warning only |
| Tenant → database | Request `ContextVar` + transaction-scoped `set_config` from a SQLAlchemy listener | wrapping the session dependency; filtering in `BaseRepository` |
| Tenant-scoped models | `TenantScoped` mixin | `@tenantable` decorator (a decorator runs after mapping and cannot add the column cleanly) |
| Migrations | Alembic operations plus an autogenerate rewriter contributed through the plugin contract | hand-written operations only |

## Package and data model

New package `packages/calango-plugins/calango-multitenancy` (`calango_multitenancy`),
depending on `calango-core`, `calango-plugin-base` and `calango-identity`, and
exposing the entry point `multitenancy` in group `calango.plugins`.

Global tables (no RLS; they are queried before a tenant is known), inheriting
`calango.db.Base`:

- `tenants`: `id`, `slug` (unique, `^[a-z0-9][a-z0-9-]{1,62}$`, and never a
  value that parses as a UUID, so a header value is unambiguously an id or a
  slug), `name`.
- `tenant_memberships`: `tenant_id` → `tenants.id`, `user_id` → `identity_users.id`,
  `role` (`owner` | `member`), unique `(tenant_id, user_id)`.

The plugin ships one Alembic revision creating both tables, declared as
`PluginMigration("multitenancy", versions, depends_on=("identity",))`.

## Public API

```python
from calango_multitenancy import (
    MultitenancyPlugin,      # MultitenancyPlugin(resolver=HeaderTenantResolver("X-Tenant-ID"))
    HeaderTenantResolver,
    TenantResolver,          # Protocol: async def resolve(request) -> str | None
    Tenant, TenantMembership,
    TenantScoped,            # mixin for tenant-owned models
    get_current_tenant,      # FastAPI dependency -> Tenant | None
    require_tenant,          # FastAPI dependency -> Tenant, 400 when none selected
    tenant_scope,            # async context manager for code outside requests
)
```

`MultitenancyPlugin.register` requires a `Calango` application on which
`IdentityPlugin` is already registered, and fails with a clear error otherwise.

### Endpoints

All require authentication (Identity's guard):

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/tenants` | Create a tenant (`slug`, `name`); the caller becomes `owner`. Duplicate slug → `409`. |
| `GET` | `/tenants` | List the caller's tenants with their role. |
| `POST` | `/tenants/{tenant_id}/members` | Owner adds a user by id as `member`. Already a member → `409`. |
| `DELETE` | `/tenants/{tenant_id}/members/{user_id}` | Owner removes a member; the last owner cannot be removed (`409`). |

Non-owners and non-members get the same `403 Tenant access denied` on the
member endpoints. Business rules live in a `TenantService` over a
`TenantRepository`, following the layered architecture.

## Request flow

### Ordered dependency guards (core change)

`Calango.add_dependency_request_guard` accepts several registrations and runs
them in registration order. The single framework-owned boundary dependency
becomes a composite whose parameters are one `Depends(registration.dependency)`
per registration, so FastAPI resolves each dependency normally: shared
sub-dependencies such as `get_current_user` are resolved once per request, and
public `dependency_overrides` of any registered dependency still apply. Starlette
routes and private mounts call the registered resolvers in the same order.
Registration after startup still fails. Existing single-guard behavior is
unchanged.

### Tenant resolution

Multitenancy registers its guard after Identity's. Its dependency depends on
`get_current_user` and:

1. asks the resolver for an identifier; none → no tenant for this request;
2. ignores the identifier when the user is anonymous (an `@public` route) → no tenant;
3. otherwise loads the tenant **and** the caller's membership in one query — by
   `id` when the identifier parses as a UUID, by `slug` otherwise;
4. returns the same `403 Tenant access denied` when the identifier is malformed,
   the tenant does not exist or the caller is not a member, so responses do not
   reveal which tenants exist.

The guard stores the tenant in `request.state.tenant` and in a module
`ContextVar`. A thin ASGI middleware installed by the plugin gives each request
a fresh tenant context and resets it afterwards, so no tenant survives into a
later request, including in-process test transports.

### Database context

The plugin registers SQLAlchemy listeners on `Session` (once per process). At the
start of every transaction on a PostgreSQL connection (`after_begin`) it runs
`SELECT set_config('app.current_tenant_id', :tenant_id, true)` with a bound
parameter: the current tenant id, or `''` when there is none (clearing any stale
value). Because a request's session can begin its transaction before the tenant
is resolved (the membership lookup may share the session), the listeners also
re-apply the setting before each statement (`do_orm_execute`) and flush
(`before_flush`) whenever the context tenant differs from the one applied in the
current transaction. The setting is transaction-local, so it is safe with
connection pools and PgBouncer transaction pooling, and it is applied again after
every `commit()`.
Every session — `get_db`, `app.database.session`, Identity's resolver, test
sessions — passes through the listener. Non-PostgreSQL connections are skipped;
startup rejects them anyway.

### Outside requests

`async with tenant_scope(tenant_id): ...` sets the tenant context for jobs,
seeds and scripts. It is trusted server code and performs no membership check.

### HTTP outcomes

| Situation | Result |
|---|---|
| `require_tenant` without a selected tenant | `400 Tenant required` |
| Malformed, unknown or non-member tenant identifier | `403 Tenant access denied` |
| Tenant-scoped table queried without a tenant | no rows; inserts rejected by RLS |

## Tenant-scoped tables

### Column

`TenantScoped` adds to a model:

```sql
tenant_id uuid NOT NULL
  DEFAULT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
  REFERENCES tenants (id)
```

with an index, and marks the table as tenant-scoped in its `info`. Inserts take
the current tenant without repositories setting it. The foreign key has no
`ON DELETE CASCADE`.

`NULLIF(..., '')` is required: after a transaction-local `set_config`, PostgreSQL
can return `''` instead of `NULL` for the setting, and `''::uuid` would raise.

### Policy

For each tenant-scoped table:

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
CREATE POLICY calango_tenant_isolation ON <table>
  USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
```

`FORCE` makes the policy apply to the table owner, which is the application role.

### Alembic integration

- The plugin registers Alembic operations `op.enable_tenant_isolation(table)` and
  `op.disable_tenant_isolation(table)` emitting the statements above and their
  reverse.
- `PluginMigration` gains an optional field `autogenerate`: a
  `process_revision_directives`-compatible rewriter. The generated `alembic/env.py`
  composes the rewriters of all installed plugins.
- The multitenancy rewriter inserts `op.enable_tenant_isolation("<table>")` right
  after each `CreateTableOp` for a tenant-scoped table. Converting an existing
  table into a tenant-scoped one remains a manual migration (backfill, then
  enable isolation), documented with an example.

### Startup checks

In the plugin lifespan, after the database starts and before serving traffic,
each failure stopping startup with a message that names the problem and the fix:

1. the database dialect is PostgreSQL;
2. the connected role has neither `SUPERUSER` nor `BYPASSRLS`;
3. every tenant-scoped table in `calango.db.Base.metadata` has row security
   enabled and forced and the `calango_tenant_isolation` policy.

## CLI

- `calango new --multitenancy` (and a wizard question) implies `--identity`,
  generates `app/plugins/multitenancy.py`, includes the plugin in `app/main.py`
  after Identity, and adds the dependency. Its Postgres setup creates a dedicated
  application role (`NOSUPERUSER NOBYPASSRLS`, owner of the database) through an
  init script; the image's superuser is used only for initialization; `.env.example`,
  `compose.yml` and CI use the application role.
- `calango generate resource Shop.Order --tenant-scoped` (and a generator
  question when multitenancy is installed) generates the model with
  `TenantScoped`.

## Error handling

- Configuration and environment problems fail at startup, never at the first
  request: missing Identity, non-PostgreSQL database, RLS-bypassing role,
  tenant-scoped table without isolation.
- Tenant identifiers never appear in error responses beyond the uniform `403`.
- Logs record tenant ids only as opaque identifiers; never membership lists or
  user e-mails.

## Testing strategy

### Unit

- ordered guards: execution order, external-path order, overrides of each
  registered dependency, single-guard compatibility;
- header resolver;
- tenant resolution outcomes: no identifier, anonymous with identifier,
  malformed, unknown and non-member (identical `403`);
- request isolation of the tenant context, including in-process transports;
- listener SQL and bound parameter, clearing without a tenant, skipping other
  dialects;
- `TenantScoped` column (type, default, foreign key, index, marker);
- Alembic operation SQL and the rewriter (only tenant-scoped `CreateTableOp`);
- plugin registration requires Identity first;
- startup checks.

Every behavioral change follows RED → GREEN → refactor.

### Integration (real PostgreSQL and Redis)

Using the shared service fixtures and a test role without `SUPERUSER` or
`BYPASSRLS`, with tenants A and B:

- a member of A reads only A's rows, including through raw SQL;
- an insert without `tenant_id` lands in A; an insert with B's id is rejected;
- non-member and unknown tenant identifiers return the same `403`;
- without a tenant, tenant-scoped listings are empty and `require_tenant` returns `400`;
- the tenant still applies after a `commit()` inside a request;
- a pooled connection reused by a request without a tenant sees no rows;
- concurrent requests for different tenants never cross;
- startup refuses a superuser role and a tenant-scoped table without forced RLS;
- the plugin migration and the isolation operations upgrade and downgrade.

### End to end

`calango new --multitenancy` → `calango generate resource Shop.Order
--tenant-scoped` → autogenerated revision → migrate as the application role →
serve → two users in two tenants, isolation verified over HTTP. The generated
project passes its own tests and static gates.

## Delivery plans

| Plan | Content |
|---|---|
| 7a | Ordered dependency guards in core; plugin package skeleton; `tenants`/`tenant_memberships` models and migration |
| 7b | Resolver, tenant guard, request context middleware, `set_config` listener, `tenant_scope`, dependencies; isolation integration tests |
| 7c | `TenantScoped`, Alembic operations and rewriter via `PluginMigration.autogenerate`, startup checks |
| 7d | Request unit of work (`get_db` commits successful requests, `DbSession`), tenant and member endpoints, `calango new --multitenancy`, `generate resource --tenant-scoped`, application role in generated projects, end-to-end test, documentation |

**Amendment (2026-10-18, during planning):** nothing in Calango committed request
transactions, so generated resources silently discarded their writes. Approved fix:
`get_db` becomes a per-request unit of work — commit when the handler succeeds,
roll back on error — exposed as `DbSession =
Annotated[AsyncSession, Depends(get_db, scope="function")]` so the commit runs
before the response is sent and a failed commit becomes an error response.

Phase 7 is complete when every repository gate passes (`ruff check`,
`ruff format --check`, `ty check packages/`, the full test suite including
integration and end-to-end tests, and `calango check:security`).
