# Phase 7C Tenant-Scoped Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give applications a `TenantScoped` mixin, Alembic operations and autogenerate support that isolate tenant tables with forced RLS, and startup checks that refuse to serve when isolation cannot hold.

**Architecture:** `TenantScoped` adds a `tenant_id` column whose server default reads the transaction's tenant setting and marks the table in column `info`. Two registered Alembic operations emit and remove the RLS policy; a `Rewriter` appends `enable_tenant_isolation` after each new tenant-scoped table, contributed to `alembic/env.py` through a new optional `PluginMigration.autogenerate` hook. A plugin lifespan verifies dialect, role and per-table isolation before traffic.

**Tech Stack:** SQLAlchemy 2 declarative mixins, Alembic 1.19 custom operations and `Rewriter`, PostgreSQL catalogs (`pg_roles`, `pg_class`, `pg_policies`).

**Spec:** `docs/superpowers/specs/2026-10-18-phase-7-multitenancy-design.md`

**Depends on:** Phases 7A and 7B.

## Global Constraints

- Test models never register on `calango.db.Base`: other suites run `Base.metadata.create_all` on SQLite, and the PostgreSQL default expression would break them. Tests declare a local `DeclarativeBase`.
- Table names reach SQL only after matching `[A-Za-z_][A-Za-z0-9_]*` and dialect quoting.
- The application runtime never imports Alembic; only `MultitenancyPlugin.migrations()` does.
- Run the four repository gates after every task.

## File Structure

| File | Responsibility |
|---|---|
| `.../calango_multitenancy/scoped.py` | `TenantScoped`, `is_tenant_scoped`, `tenant_scoped_tables`, shared SQL fragments |
| `.../calango_multitenancy/migration_ops.py` | Alembic operations, renderers, `tenant_isolation_rewriter` |
| `.../calango_multitenancy/checks.py` | `verify_tenant_isolation` |
| `packages/calango-plugin-base/calango_plugin_base/__init__.py` | `PluginMigration.autogenerate` |
| `packages/calango-cli/calango_cli/migrations.py` | validate the hook, `compose_autogenerate` |
| `packages/calango-cli/calango_cli/templates/alembic/env.py.jinja` | pass composed hooks to `context.configure` |

---

### Task 1: `TenantScoped` mixin

**Files:**
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/scoped.py`
- Modify: `.../calango_multitenancy/__init__.py`
- Test: `packages/calango-plugins/calango-multitenancy/tests/test_scoped.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from uuid import UUID, uuid4

from calango_multitenancy import TenantScoped
from calango_multitenancy.scoped import is_tenant_scoped, tenant_scoped_tables
from sqlalchemy import ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class LocalBase(DeclarativeBase):
    metadata = MetaData()


class LocalTenant(LocalBase):
    __tablename__ = "tenants"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Order(TenantScoped, LocalBase):
    __tablename__ = "orders"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    item: Mapped[str] = mapped_column(String(50))


class Product(LocalBase):
    __tablename__ = "products"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_ref: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))


def test_tenant_scoped_adds_a_defaulted_indexed_tenant_column():
    column = Order.__table__.c.tenant_id
    assert column.nullable is False
    assert column.index is True
    assert {fk.target_fullname for fk in column.foreign_keys} == {"tenants.id"}
    assert all(fk.ondelete is None for fk in column.foreign_keys)
    default = str(column.server_default.arg)
    assert "current_setting('app.current_tenant_id', true)" in default
    assert "NULLIF" in default


def test_only_marked_tables_are_tenant_scoped():
    assert is_tenant_scoped(Order.__table__)
    assert not is_tenant_scoped(Product.__table__)
    assert [table.name for table in tenant_scoped_tables(LocalBase.metadata)] == ["orders"]
```

- [ ] **Step 2: Prove RED** — `uv run pytest packages/calango-plugins/calango-multitenancy/tests/test_scoped.py -q` → `ImportError: cannot import name 'TenantScoped'`.

- [ ] **Step 3: Implement `scoped.py`**

```python
"""Tenant-owned tables: the ``tenant_id`` column and how to recognize it."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, MetaData, Table, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

TENANT_SCOPED_INFO_KEY = "calango.tenant_scoped"
POLICY_NAME = "calango_tenant_isolation"
# NULLIF: after a transaction-local set_config, PostgreSQL may report '' rather
# than NULL, and ''::uuid would raise instead of matching no tenant.
CURRENT_TENANT_SQL = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


class TenantScoped:
    """Mixin for tenant-owned models.

    Adds ``tenant_id``, filled by the database from the current request's tenant,
    and marks the table so migrations and startup checks enforce isolation.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("tenants.id"),
            index=True,
            nullable=False,
            server_default=text(CURRENT_TENANT_SQL),
            info={TENANT_SCOPED_INFO_KEY: True},
        )


def is_tenant_scoped(table: Table) -> bool:
    column = table.columns.get("tenant_id")
    return column is not None and bool(column.info.get(TENANT_SCOPED_INFO_KEY))


def tenant_scoped_tables(metadata: MetaData) -> list[Table]:
    return [table for table in metadata.sorted_tables if is_tenant_scoped(table)]
```

Export `TenantScoped` from `__init__.py`.

- [ ] **Step 4: Prove GREEN and commit**

```bash
git add packages/calango-plugins/calango-multitenancy
git commit -m "feat(multitenancy): add the TenantScoped model mixin"
```

### Task 2: Alembic isolation operations

**Files:**
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/migration_ops.py`
- Modify: `packages/calango-plugins/calango-multitenancy/pyproject.toml` (add `"alembic>=1.14"`)
- Test: `packages/calango-plugins/calango-multitenancy/tests/test_migration_ops.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from io import StringIO

import pytest
from alembic.autogenerate import render_python_code
from alembic.migration import MigrationContext
from alembic.operations import Operations, ops
from calango_multitenancy.migration_ops import DisableTenantIsolationOp, EnableTenantIsolationOp


def _offline_sql(apply) -> str:
    buffer = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": buffer},
    )
    apply(Operations(context))
    return buffer.getvalue()


def test_enable_forces_rls_and_creates_the_policy():
    sql = _offline_sql(lambda op: op.enable_tenant_isolation("orders"))
    assert "ALTER TABLE orders ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE orders FORCE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY calango_tenant_isolation ON orders" in sql
    assert sql.count("NULLIF(current_setting('app.current_tenant_id', true), '')::uuid") == 2


def test_disable_drops_the_policy_and_rls():
    sql = _offline_sql(lambda op: op.disable_tenant_isolation("orders"))
    assert "DROP POLICY IF EXISTS calango_tenant_isolation ON orders" in sql
    assert "ALTER TABLE orders NO FORCE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE orders DISABLE ROW LEVEL SECURITY" in sql


def test_operations_reverse_each_other():
    assert isinstance(EnableTenantIsolationOp("orders").reverse(), DisableTenantIsolationOp)
    assert isinstance(DisableTenantIsolationOp("orders").reverse(), EnableTenantIsolationOp)


@pytest.mark.parametrize("name", ["orders; DROP TABLE users", "1orders", "orders-x", ""])
def test_unsafe_table_names_are_rejected(name):
    with pytest.raises(ValueError, match="table name"):
        _offline_sql(lambda op: op.enable_tenant_isolation(name))


def test_operations_render_into_autogenerated_revisions():
    code = render_python_code(
        ops.UpgradeOps(ops=[EnableTenantIsolationOp("orders"), DisableTenantIsolationOp("x")])
    )
    assert "op.enable_tenant_isolation('orders')" in code
    assert "op.disable_tenant_isolation('x')" in code
```

- [ ] **Step 2: Prove RED** — `uv run pytest packages/calango-plugins/calango-multitenancy/tests/test_migration_ops.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `migration_ops.py`**

```python
"""Alembic support for tenant isolation. Imported only by migration tooling."""

from __future__ import annotations

import re
from typing import Any

from alembic.autogenerate import renderers
from alembic.autogenerate.rewriter import Rewriter
from alembic.operations import MigrateOperation, Operations, ops

from calango_multitenancy.scoped import CURRENT_TENANT_SQL, POLICY_NAME, is_tenant_scoped

_TABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _quoted_table(operations: Operations, table_name: str) -> str:
    """Validate and quote a table name; identifiers cannot be bound parameters."""
    if _TABLE_NAME.fullmatch(table_name) is None:
        raise ValueError(f"Invalid table name for tenant isolation: {table_name!r}")
    return operations.get_context().dialect.identifier_preparer.quote(table_name)


@Operations.register_operation("enable_tenant_isolation")
class EnableTenantIsolationOp(MigrateOperation):
    """Enable and force RLS on a tenant-scoped table and create its policy."""

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name

    @classmethod
    def enable_tenant_isolation(cls, operations: Operations, table_name: str) -> Any:
        return operations.invoke(cls(table_name))

    def reverse(self) -> DisableTenantIsolationOp:
        return DisableTenantIsolationOp(self.table_name)


@Operations.register_operation("disable_tenant_isolation")
class DisableTenantIsolationOp(MigrateOperation):
    """Drop the tenant policy and turn RLS off on a table."""

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name

    @classmethod
    def disable_tenant_isolation(cls, operations: Operations, table_name: str) -> Any:
        return operations.invoke(cls(table_name))

    def reverse(self) -> EnableTenantIsolationOp:
        return EnableTenantIsolationOp(self.table_name)


@Operations.implementation_for(EnableTenantIsolationOp)
def _enable(operations: Operations, operation: EnableTenantIsolationOp) -> None:
    table = _quoted_table(operations, operation.table_name)
    condition = "tenant_id = " + CURRENT_TENANT_SQL
    statements = (
        "ALTER TABLE " + table + " ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE " + table + " FORCE ROW LEVEL SECURITY",
        "CREATE POLICY " + POLICY_NAME + " ON " + table
        + " USING (" + condition + ") WITH CHECK (" + condition + ")",
    )
    for statement in statements:
        operations.execute(statement)


@Operations.implementation_for(DisableTenantIsolationOp)
def _disable(operations: Operations, operation: DisableTenantIsolationOp) -> None:
    table = _quoted_table(operations, operation.table_name)
    statements = (
        "DROP POLICY IF EXISTS " + POLICY_NAME + " ON " + table,
        "ALTER TABLE " + table + " NO FORCE ROW LEVEL SECURITY",
        "ALTER TABLE " + table + " DISABLE ROW LEVEL SECURITY",
    )
    for statement in statements:
        operations.execute(statement)


@renderers.dispatch_for(EnableTenantIsolationOp)
def _render_enable(_autogen_context: Any, operation: EnableTenantIsolationOp) -> str:
    return f"op.enable_tenant_isolation({operation.table_name!r})"


@renderers.dispatch_for(DisableTenantIsolationOp)
def _render_disable(_autogen_context: Any, operation: DisableTenantIsolationOp) -> str:
    return f"op.disable_tenant_isolation({operation.table_name!r})"


tenant_isolation_rewriter = Rewriter()


@tenant_isolation_rewriter.rewrites(ops.CreateTableOp)
def _isolate_new_tenant_tables(context: Any, _revision: Any, operation: ops.CreateTableOp) -> Any:
    """Append ``enable_tenant_isolation`` after creating a tenant-scoped table."""
    metadata = context.opts.get("target_metadata")
    key = (
        operation.table_name
        if operation.schema is None
        else f"{operation.schema}.{operation.table_name}"
    )
    table = None if metadata is None else metadata.tables.get(key)
    if table is None or not is_tenant_scoped(table):
        return operation
    return [operation, EnableTenantIsolationOp(operation.table_name)]
```

Add `"alembic>=1.14"` to the plugin's dependencies (the module imports it), then `uv lock`.

- [ ] **Step 4: Prove GREEN, run Opengrep, commit**

Run the tests (PASS) and `uv run calango check:security` (no findings — statements are built from a validated, quoted identifier and executed as a variable, not an interpolated literal).

```bash
git add packages/calango-plugins/calango-multitenancy uv.lock
git commit -m "feat(multitenancy): add Alembic tenant isolation operations"
```

### Task 3: Autogenerate hook through the plugin contract

**Files:**
- Modify: `packages/calango-plugin-base/calango_plugin_base/__init__.py`
- Modify: `packages/calango-cli/calango_cli/migrations.py`
- Modify: `packages/calango-cli/calango_cli/templates/alembic/env.py.jinja`
- Modify: `.../calango_multitenancy/plugin.py`
- Test: `packages/calango-plugin-base/tests/test_plugin_base.py`, `packages/calango-cli/tests/test_db_command.py`, `packages/calango-plugins/calango-multitenancy/tests/test_rewriter.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/calango-plugin-base/tests/test_plugin_base.py`:

```python
def test_plugin_migration_autogenerate_defaults_to_none(tmp_path):
    from calango_plugin_base import PluginMigration

    assert PluginMigration("demo", tmp_path, ()).autogenerate is None

    def hook(context, revision, directives) -> None:
        pass

    assert PluginMigration("demo", tmp_path, (), autogenerate=hook).autogenerate is hook
```

Append to `packages/calango-cli/tests/test_db_command.py`:

```python
def test_compose_autogenerate_runs_plugin_hooks_in_order(tmp_path):
    from calango_cli.migrations import compose_autogenerate

    calls: list[str] = []

    def first(_context, _revision, _directives) -> None:
        calls.append("first")

    def second(_context, _revision, _directives) -> None:
        calls.append("second")

    items = (
        PluginMigration("a", tmp_path, (), autogenerate=first),
        PluginMigration("b", tmp_path, ()),
        PluginMigration("c", tmp_path, (), autogenerate=second),
    )
    hook = compose_autogenerate(items)
    assert hook is not None
    hook(None, None, [])
    assert calls == ["first", "second"]
    assert compose_autogenerate((PluginMigration("b", tmp_path, ()),)) is None


def test_non_callable_autogenerate_hook_is_rejected(tmp_path):
    with pytest.raises(MigrationConfigurationError, match="autogenerate"):
        validate_migration_descriptors(
            (PluginMigration("a", tmp_path, (), autogenerate="not callable"),)  # ty: ignore[invalid-argument-type]
        )
```

(add `validate_migration_descriptors` to that file's `calango_cli.migrations` import.)

`packages/calango-plugins/calango-multitenancy/tests/test_rewriter.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from alembic.operations import ops
from calango_multitenancy import MultitenancyPlugin, TenantScoped
from calango_multitenancy.migration_ops import EnableTenantIsolationOp, tenant_isolation_rewriter
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class LocalBase(DeclarativeBase):
    metadata = MetaData()


class LocalTenant(LocalBase):
    __tablename__ = "tenants"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Invoice(TenantScoped, LocalBase):
    __tablename__ = "invoices"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


def test_rewriter_isolates_only_new_tenant_scoped_tables():
    upgrade = ops.UpgradeOps(
        ops=[
            ops.CreateTableOp.from_table(LocalTenant.__table__),
            ops.CreateTableOp.from_table(Invoice.__table__),
        ]
    )
    script = ops.MigrationScript("rev", upgrade, ops.DowngradeOps(ops=[]))
    context = SimpleNamespace(opts={"target_metadata": LocalBase.metadata})

    tenant_isolation_rewriter(context, None, [script])

    produced = script.upgrade_ops.ops
    assert [type(item).__name__ for item in produced] == [
        "CreateTableOp",
        "CreateTableOp",
        "EnableTenantIsolationOp",
    ]
    assert isinstance(produced[2], EnableTenantIsolationOp)
    assert produced[2].table_name == "invoices"


def test_plugin_contributes_the_rewriter():
    (descriptor,) = MultitenancyPlugin().migrations()
    assert descriptor.autogenerate is tenant_isolation_rewriter
```

- [ ] **Step 2: Prove RED** — run the three test files; expect `TypeError: ... unexpected keyword argument 'autogenerate'` and `ImportError: compose_autogenerate`.

- [ ] **Step 3: Extend `PluginMigration`**

```python
from collections.abc import Callable
from typing import Any

AutogenerateHook = Callable[[Any, Any, list[Any]], None]


@dataclass(frozen=True)
class PluginMigration:
    """A wheel-safe Alembic migration contribution from a plugin.

    ``autogenerate`` is an optional ``process_revision_directives`` hook that the
    generated ``alembic/env.py`` runs during ``calango db revision``.
    """

    name: str
    versions: Traversable
    depends_on: tuple[str, ...]
    autogenerate: AutogenerateHook | None = None
```

Export `AutogenerateHook` in `__all__`.

- [ ] **Step 4: Validate and compose hooks in `calango_cli/migrations.py`**

Inside `_descriptor_tuple`, after the `depends_on` checks:

```python
        if item.autogenerate is not None and not callable(item.autogenerate):
            raise _plugin_error(item.name, "autogenerate must be callable")
```

New public function:

```python
def compose_autogenerate(
    items: Iterable[PluginMigration],
) -> Callable[[Any, Any, list[Any]], None] | None:
    """Combine plugin ``process_revision_directives`` hooks, in plugin order."""
    hooks = tuple(item.autogenerate for item in items if item.autogenerate is not None)
    if not hooks:
        return None

    def process_revision_directives(context: Any, revision: Any, directives: list[Any]) -> None:
        for hook in hooks:
            hook(context, revision, directives)

    return process_revision_directives
```

(import `Callable`/`Any` as needed).

- [ ] **Step 5: Use the hooks in the generated `env.py`**

In `templates/alembic/env.py.jinja`, add `compose_autogenerate` to the
`from calango_cli.migrations import (...)` block, then replace the plugin
location block and both `context.configure(...)` calls:

```python
try:
    plugin_migrations = load_plugin_migrations()
    plugin_locations = own_version_locations(config, plugin_migrations)
    configured_locations = config.get_main_option("version_locations")
    all_locations = (
        *configured_locations.split(os.pathsep),
        *(str(path) for path in plugin_locations),
    )
    config.set_main_option("version_locations", os.pathsep.join(all_locations))
    refresh_alembic_script(config, context.script)
except MigrationConfigurationError as exc:
    raise CommandError(str(exc)) from None

process_revision_directives = compose_autogenerate(plugin_migrations)
import_models("app.contexts")
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        process_revision_directives=process_revision_directives,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        process_revision_directives=process_revision_directives,
    )
    with context.begin_transaction():
        context.run_migrations()
```

Then run `uv run pytest packages/calango-cli -q`: `test_new_project_passes_its_own_ruff_gates` and `test_generated_alembic_env_loads_plugins_before_metadata` must still pass (the latter's fake `context.configure` accepts `**kwargs`).

- [ ] **Step 6: Contribute the rewriter from the plugin**

```python
    def migrations(self) -> tuple[PluginMigration, ...]:
        """Tenant tables run after Identity; autogenerate isolates new tenant tables."""
        from calango_multitenancy.migration_ops import tenant_isolation_rewriter

        versions = files("calango_multitenancy.migrations.versions")
        return (
            PluginMigration(
                "multitenancy",
                versions,
                ("identity",),
                autogenerate=tenant_isolation_rewriter,
            ),
        )
```

The import inside the method keeps Alembic out of the application runtime and registers the operations before any revision runs.

- [ ] **Step 7: Prove GREEN, run all gates, commit**

```bash
git add packages/calango-plugin-base packages/calango-cli packages/calango-plugins/calango-multitenancy
git commit -m "feat(multitenancy): isolate new tenant tables in autogenerated revisions"
```

### Task 4: Startup isolation checks

**Files:**
- Create: `packages/calango-plugins/calango-multitenancy/calango_multitenancy/checks.py`
- Modify: `.../calango_multitenancy/plugin.py`
- Test: `packages/calango-plugins/calango-multitenancy/tests/integration/test_startup_checks.py`, `packages/calango-plugins/calango-multitenancy/tests/test_checks.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_checks.py` (no PostgreSQL needed):

```python
from __future__ import annotations

import pytest
from calango_multitenancy.checks import verify_tenant_isolation
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


async def test_non_postgresql_databases_are_refused():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(RuntimeError, match="requires PostgreSQL"):
                await verify_tenant_isolation(session, MetaData())
    finally:
        await engine.dispose()
```

`tests/integration/test_startup_checks.py`:

```python
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from calango_multitenancy import TenantScoped
from calango_multitenancy.checks import verify_tenant_isolation
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

pytestmark = pytest.mark.integration


class LocalBase(DeclarativeBase):
    metadata = MetaData()


class Ledger(TenantScoped, LocalBase):
    __tablename__ = "ledgers"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


async def _verify(url: str, metadata: MetaData) -> None:
    engine = create_async_engine(url)
    try:
        async with AsyncSession(engine) as session:
            await verify_tenant_isolation(session, metadata)
    finally:
        await engine.dispose()


async def test_a_role_that_bypasses_rls_is_refused(postgres_url):
    # The Docker fixture connects as the image superuser.
    with pytest.raises(RuntimeError, match="bypasses row-level security"):
        await _verify(postgres_url, MetaData())


async def test_unisolated_tenant_table_is_refused_until_isolated(tenant_database):
    engine = create_async_engine(tenant_database)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE ledgers (id uuid PRIMARY KEY, "
                    "tenant_id uuid NOT NULL REFERENCES tenants (id))"
                )
            )
    finally:
        await engine.dispose()

    with pytest.raises(RuntimeError, match="ledgers"):
        await _verify(tenant_database, LocalBase.metadata)

    engine = create_async_engine(tenant_database)
    try:
        async with engine.begin() as connection:
            for statement in (
                "ALTER TABLE ledgers ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE ledgers FORCE ROW LEVEL SECURITY",
                "CREATE POLICY calango_tenant_isolation ON ledgers USING (true)",
            ):
                await connection.execute(text(statement))
    finally:
        await engine.dispose()

    await _verify(tenant_database, LocalBase.metadata)


async def test_lifespan_refuses_to_start_as_superuser(postgres_url, identity_plugin):
    from calango_multitenancy import MultitenancyPlugin

    from calango import Calango
    from calango.config import CalangoSettings, DatabaseSettings, SecuritySettings

    app = Calango(
        settings=CalangoSettings(
            database=DatabaseSettings(URL=postgres_url),
            security=SecuritySettings(SECRET_KEY="integration-secret"),
        )
    )
    app.include_plugin(identity_plugin)
    app.include_plugin(MultitenancyPlugin())

    with pytest.raises(RuntimeError, match="bypasses row-level security"):
        async with app.router.lifespan_context(app):
            pass
```

(`tenant_database` comes from the 7B integration `conftest.py`.)

- [ ] **Step 2: Prove RED** — `ModuleNotFoundError: calango_multitenancy.checks`.

- [ ] **Step 3: Implement `checks.py`**

```python
"""Refuse to serve when PostgreSQL cannot enforce tenant isolation."""

from __future__ import annotations

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncSession

from calango_multitenancy.scoped import POLICY_NAME, tenant_scoped_tables

_ROLE_BYPASSES_RLS = text(
    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
)
_TABLE_ISOLATION = text(
    "SELECT c.relrowsecurity, c.relforcerowsecurity, "
    "EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = n.nspname "
    "AND p.tablename = c.relname AND p.policyname = :policy) "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relname = :table AND n.nspname = current_schema()"
)


async def verify_tenant_isolation(session: AsyncSession, metadata: MetaData) -> None:
    """Raise ``RuntimeError`` naming the problem and its fix, or return when isolated."""
    connection = await session.connection()
    if connection.dialect.name != "postgresql":
        raise RuntimeError(
            "calango-multitenancy requires PostgreSQL row-level security; "
            f"the configured database is {connection.dialect.name}"
        )
    if (await session.execute(_ROLE_BYPASSES_RLS)).scalar_one():
        raise RuntimeError(
            "The database role bypasses row-level security (SUPERUSER or BYPASSRLS); "
            "connect as a role without those attributes"
        )
    for table in tenant_scoped_tables(metadata):
        row = (
            await session.execute(_TABLE_ISOLATION, {"table": table.name, "policy": POLICY_NAME})
        ).one_or_none()
        if row is None or not all(row):
            raise RuntimeError(
                f"Tenant-scoped table '{table.name}' is not isolated; run `calango db migrate`, "
                f"or add op.enable_tenant_isolation('{table.name}') to its migration"
            )
```

- [ ] **Step 4: Run the checks from the plugin lifespan**

In `plugin.py` `register(...)`, after the guard registration:

```python
        @asynccontextmanager
        async def verify_isolation(running_app: Calango) -> AsyncIterator[None]:
            session_dependency = running_app.database.session
            open_sessions = running_app.dependency_overrides.get(
                session_dependency, session_dependency
            )
            async with aclosing(open_sessions()) as sessions:
                async for session in sessions:
                    await verify_tenant_isolation(session, Base.metadata)
                    break
            yield

        app.add_plugin_lifespan(verify_isolation)
```

(imports: `asynccontextmanager`, `aclosing`, `AsyncIterator`, `from calango.db import Base`, `verify_tenant_isolation`). Plugin lifespans start after `app.database.start()`, so the engine exists.

- [ ] **Step 5: Prove GREEN (including the 7B isolation suite, whose lifespan now runs the checks), run all gates, commit**

```bash
git add packages/calango-plugins/calango-multitenancy
git commit -m "feat(multitenancy): refuse to start without enforceable isolation"
```
