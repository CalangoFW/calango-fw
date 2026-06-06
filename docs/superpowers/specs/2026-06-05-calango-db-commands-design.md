# Calango DB commands + canonical Base — Design

> Status: Approved for implementation
> Phase: 5 (M2 — "generate resource")
> Branch: feature/db-commands

---

## Overview

Phase 5 closes the M2 gap: a project scaffolded by `calango new` configures Alembic
but has no way to create, apply, or roll back migrations through the framework, and
no seed mechanism. This adds the `calango db` command group and the missing
foundation it depends on — a **canonical SQLAlchemy `Base`** in calango-core so that
Alembic autogenerate can see every model across all contexts.

The blocker this fixes: today each generated model declares its own
`class Base(DeclarativeBase)`, so there is no single `Base.metadata` for Alembic to
target. Autogenerate is impossible until models share one Base.

---

## Design decisions (approved)

| Decision | Choice |
|---|---|
| Scope | Full flow: `revision` (autogenerate) + `migrate` + `rollback` + `seed` |
| Canonical Base | `calango.db.Base` with `id` (UUID PK), `created_at`, `updated_at` baked in |
| Model discovery | **Approach A — auto-discovery**: `import_models()` walks the contexts package |
| Seeds | `app/seeds/` directory with ordered modules, each `async def seed(session)` |
| Identity plugin | Left as-is — plugins own their migrations via `PluginBase.migrations()` |
| `db suggest-indexes` | Deferred (needs `pg_stat_statements`) |

---

## Component 1 — `calango.db` (calango-core)

New module `packages/calango-core/calango/db/__init__.py`:

```python
class Base(DeclarativeBase):
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def import_models(package: str = "app.contexts") -> None:
    """Import every `models` submodule under `package` so each model registers on
    Base.metadata. Used by Alembic env.py so autogenerate sees all contexts.
    Walks <package>/*/models/*.py via importlib + pkgutil. No-op for absent packages."""
```

- `import_models` is generic (takes a package path) and unit-tested in calango-core
  against a fixture package — it does not import `app.contexts` directly.
- `BaseRepository` is bound to the canonical Base: `class BaseRepository[T: Base]`.
  This makes `self.model.id` resolve in the type checker — the `# ty: ignore` on
  `get_for_update` is removed. `test_repository.py` / `test_service.py` test models
  switch to `calango.db.Base`; their `id` therefore moves from `str` to `UUID`
  (SQLAlchemy maps UUID on SQLite via its `Uuid` type), which also removes the
  `# ty: ignore[invalid-argument-type]` on the `repository.get(item.id)` call in
  `test_service.py`. Net: two ty-ignores deleted, not added.

Tests: `packages/calango-core/tests/test_db.py` — Base has the three columns;
`import_models` registers models from a fixture package; bound repository resolves `.id`.

---

## Component 2 — `calango db` command group (calango-cli)

New `packages/calango-cli/calango_cli/commands/db.py`, registered as a Typer group in
`main.py`: `app.add_typer(db_app, name="db")`. Mirrors the `check.py` pattern (resolve
the executable via `shutil.which`, subprocess with fixed args, Rich output via `ui.py`,
propagate exit codes).

| Command | Action |
|---|---|
| `calango db revision -m "msg"` | `alembic revision --autogenerate -m "msg"` |
| `calango db migrate` | `alembic upgrade head` |
| `calango db rollback [--step N]` | `alembic downgrade -N` (default 1) |
| `calango db seed` | import `app/seeds/*.py` sorted by name, run each `async def seed(session)` in a transaction |

- `revision`/`migrate`/`rollback` shell out to `uv run alembic ...` in the project dir.
- `seed` discovers `app/seeds/[0-9]*_*.py` (sorted), imports each, awaits its `seed(session)`
  inside a session from the project's DB config; each module commits in its own transaction.
- Guard: each command checks it is run inside a project (`alembic.ini` present for the
  alembic wrappers; `app/seeds/` for seed) and exits 1 with a hint otherwise.

Tests: `packages/calango-cli/tests/test_db_command.py` — mock subprocess for the alembic
wrappers (assert correct argv + exit code), a temp `app/seeds/` for seed ordering, `--help`,
and the not-a-project guards.

---

## Component 3 — Template changes (calango-cli)

- `templates/resource/model.py.jinja` — replace the local Base + id/created_at/updated_at
  with `from calango.db import Base`; model keeps only `__tablename__` and business fields.
- `templates/alembic/env.py.jinja` — `from calango.db import Base, import_models`,
  call `import_models("app.contexts")`, set `target_metadata = Base.metadata`.
- New `templates/app/seeds/__init__.py.jinja` and `templates/app/seeds/001_example.py.jinja`
  (a commented, idempotent example `async def seed(session)`), registered in `new.py`
  `_TEMPLATE_FILES`.
- Generated `pyproject.toml` already lists calango-core; importing `calango.db` works.

Tests added to `test_new_command.py`: model imports `calango.db.Base`; env.py wires
`target_metadata = Base.metadata`; `app/seeds/001_example.py` exists.

---

## Component 4 — Scope boundaries

- **Identity plugin untouched.** Its own `Base` is intentional — plugins ship migrations
  via `PluginBase.migrations()`, so identity tables are not part of the app's autogenerate.
- **`db suggest-indexes` deferred** — separate iteration; needs `pg_stat_statements` analysis.
- **No new runtime dependency** — Alembic is already a generated-project dependency; the
  commands are thin wrappers.

---

## Verification (end-to-end)

```bash
# calango-core
uv run pytest packages/calango-core/ -q          # Base + import_models + bound repository
uv run ty check packages/                         # the get_for_update ty:ignore is gone

# generated project
uv run calango new demo --path /tmp
uv run calango generate resource Shop.Order --path /tmp/demo
cd /tmp/demo
uv run calango db revision -m "add orders"        # autogenerate produces a migration with the orders table
uv run calango db migrate                          # applies it
uv run calango db rollback                          # reverts one
uv run calango db seed                              # runs app/seeds/ in order

# CLI suite + quality + security
uv run pytest packages/calango-cli/ -q
uv run ruff check . && uv run ty check packages/ && calango check:security
```

The autogenerated migration containing the `orders` table (proving `import_models` +
`target_metadata` work across contexts) is the key success signal.

---

## Files changed

**calango-core:** `calango/db/__init__.py` (new), `calango/repository/__init__.py`
(bind `T: Base`, drop ty:ignore), `tests/test_db.py` (new), `tests/test_repository.py`
+ `tests/test_service.py` (test models use `calango.db.Base`).

**calango-cli:** `calango_cli/commands/db.py` (new), `calango_cli/main.py` (register),
`tests/test_db_command.py` (new); templates: `resource/model.py.jinja`,
`alembic/env.py.jinja`, `app/seeds/*` (new) + `commands/new.py` registration;
`tests/test_new_command.py` (assertions).

**docs:** ROADMAP Phase 5 → Done; CLAUDE.md (db commands + canonical Base convention);
README (component status).
