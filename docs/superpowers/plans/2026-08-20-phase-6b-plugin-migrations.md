# Phase 6B Plugin Migrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a typed plugin migration contract and ship executable Identity migrations over canonical metadata.

**Architecture:** Plugins return wheel-safe `Traversable` version locations. The CLI validates a dependency graph, materializes Alembic version paths, and imports plugin models into `calango.db.Base.metadata`.

**Tech Stack:** Python 3.12, importlib.resources, Alembic, SQLAlchemy, PostgreSQL, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-phase-6-technical-debt-remediation-design.md`

## Global Constraints

- Descriptor shape is `PluginMigration(name: str, versions: Traversable, depends_on: tuple[str, ...])`.
- Duplicate names, absent dependencies, and cycles fail before Alembic runs.
- Identity uses only `calango.db.Base`; PostgreSQL upgrade and downgrade are release evidence.

---

### Task 1: Typed migration descriptor and graph validation

**Files:**
- Modify: `packages/calango-plugin-base/calango_plugin_base/__init__.py`
- Modify: `packages/calango-plugin-base/tests/test_plugin_base.py`
- Modify: `packages/calango-core/tests/test_app.py`

**Interfaces:**
- Produces: frozen `PluginMigration`; `PluginBase.migrations() -> tuple[PluginMigration, ...]`.

- [ ] **Step 1: Test descriptor immutability and protocol shape**

```python
def test_plugin_migration_is_immutable(tmp_path):
    item = PluginMigration("identity", tmp_path, ())
    with pytest.raises(FrozenInstanceError):
        item.name = "changed"
```

Update fake plugins in core tests to return `()`.

- [ ] **Step 2: Prove RED, implement, and prove GREEN**

Run: `uv run pytest packages/calango-plugin-base/tests packages/calango-core/tests/test_app.py -v`
Expected before implementation: import failure for `PluginMigration`; after adding the frozen dataclass and protocol return type: PASS.

```bash
git add packages/calango-plugin-base packages/calango-core/tests/test_app.py
git commit -m "feat(plugins): type migration contributions"
```

### Task 2: Identity canonical models and packaged revision

**Files:**
- Modify: `packages/calango-plugins/calango-identity/calango_identity/models.py`
- Create: `packages/calango-plugins/calango-identity/calango_identity/migrations/__init__.py`
- Create: `packages/calango-plugins/calango-identity/calango_identity/migrations/versions/0001_identity.py`
- Modify: `packages/calango-plugins/calango-identity/calango_identity/plugin.py`
- Modify: `packages/calango-plugins/calango-identity/pyproject.toml`
- Modify: `packages/calango-plugins/calango-identity/tests/test_models.py`
- Create: `packages/calango-plugins/calango-identity/tests/test_migrations.py`

**Interfaces:**
- Consumes: `PluginMigration` and `calango.db.Base`.
- Produces: `IdentityPlugin.migrations()` returning one descriptor named `identity`.

- [ ] **Step 1: Add failing metadata/package tests**

```python
def test_identity_uses_canonical_metadata():
    assert User.metadata is CalangoBase.metadata
    assert set(IDENTITY_TABLES) <= set(CalangoBase.metadata.tables)

def test_identity_migration_resource_exists():
    descriptor, = IdentityPlugin(settings=settings, refresh_store=store).migrations()
    assert descriptor.name == "identity"
    assert descriptor.versions.joinpath("0001_identity.py").is_file()
```

- [ ] **Step 2: Prove RED**

Run: `uv run pytest packages/calango-plugins/calango-identity/tests/test_models.py packages/calango-plugins/calango-identity/tests/test_migrations.py -v`
Expected: separate metadata and missing resource.

- [ ] **Step 3: Implement canonical models and exact revision**

Remove the local base, import `Base` from `calango.db`, add `calango-core` to dependencies and workspace sources, and create revision `identity_0001` whose `upgrade()` creates users, roles, permissions, user_roles, role_permissions with current model columns, unique constraints, indexes, and cascade foreign keys; `downgrade()` drops them in reverse order. Return `PluginMigration("identity", files("calango_identity.migrations.versions"), ())`.

- [ ] **Step 4: Prove GREEN and commit**

Run: `uv run pytest packages/calango-plugins/calango-identity/tests/test_models.py packages/calango-plugins/calango-identity/tests/test_migrations.py -v`
Expected: PASS and wheel metadata includes both runtime dependencies.

```bash
git add packages/calango-plugins/calango-identity
git commit -m "feat(identity): ship canonical database migration"
```

### Task 3: CLI migration discovery and PostgreSQL proof

**Files:**
- Create: `packages/calango-cli/calango_cli/migrations.py`
- Modify: `packages/calango-cli/calango_cli/templates/alembic/env.py.jinja`
- Modify: `packages/calango-cli/calango_cli/templates/alembic.ini.jinja`
- Modify: `packages/calango-cli/tests/test_db_command.py`
- Create: `packages/calango-plugins/calango-identity/tests/integration/test_postgres_migrations.py`

**Interfaces:**
- Produces: `order_migrations(items) -> tuple[PluginMigration, ...]` and `version_locations(items) -> tuple[Path, ...]`.

- [ ] **Step 1: Add failing graph and database tests**

```python
def test_order_rejects_cycle(tmp_path):
    items = (PluginMigration("a", tmp_path, ("b",)), PluginMigration("b", tmp_path, ("a",)))
    with pytest.raises(MigrationConfigurationError, match="cycle"):
        order_migrations(items)

async def test_identity_upgrade_and_downgrade(postgres_url):
    await run_alembic(postgres_url, "upgrade", "heads")
    assert await table_names(postgres_url) >= IDENTITY_TABLES
    await run_alembic(postgres_url, "downgrade", "base")
    assert not (await table_names(postgres_url) & IDENTITY_TABLES)
```

- [ ] **Step 2: Prove RED, implement, and prove GREEN**

Run graph tests first; implement deterministic topological sorting and safe errors naming the plugin. Update generated `env.py` to load configured plugin entry points, validate descriptors, set Alembic `version_locations`, and import plugin models before assigning `Base.metadata`.

Run: `uv run pytest packages/calango-cli/tests/test_db_command.py -v`
Expected: PASS.

Run with services: `uv run pytest packages/calango-plugins/calango-identity/tests/integration/test_postgres_migrations.py -v`
Expected: PASS against PostgreSQL.

```bash
git add packages/calango-cli packages/calango-plugins/calango-identity/tests/integration
git commit -m "feat(cli): discover plugin migration graphs"
```
