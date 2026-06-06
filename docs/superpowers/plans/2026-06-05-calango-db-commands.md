# Calango DB commands + canonical Base — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `calango db` command group (revision/migrate/rollback/seed) plus the canonical `calango.db.Base` it depends on, so a generated project can create and run Alembic migrations across all contexts.

**Architecture:** A single `calango.db.Base` unifies model metadata; `import_models()` auto-discovers context models so Alembic autogenerate sees them. The `calango db` CLI group wraps Alembic (subprocess) and runs ordered seed modules. Templates are updated so generated models inherit the canonical Base and the Alembic env wires `target_metadata`.

**Tech Stack:** SQLAlchemy 2 (async), Alembic, Typer, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-06-05-calango-db-commands-design.md`

**Branch:** `feature/db-commands` (create via superpowers:using-git-worktrees before Task 1).

---

## File structure

| File | Responsibility |
|---|---|
| `packages/calango-core/calango/db/__init__.py` | Canonical `Base` + `import_models()` |
| `packages/calango-core/tests/test_db.py` | Tests for Base columns + discovery |
| `packages/calango-core/calango/repository/__init__.py` | Bind `BaseRepository[T: Base]`, drop ty:ignore |
| `packages/calango-core/tests/test_repository.py`, `test_service.py` | Test models → `calango.db.Base` |
| `packages/calango-cli/calango_cli/commands/db.py` | `calango db` Typer group |
| `packages/calango-cli/calango_cli/main.py` | Register the group |
| `packages/calango-cli/tests/test_db_command.py` | Command tests |
| `packages/calango-cli/calango_cli/templates/resource/model.py.jinja` | Lean model (inherit Base) |
| `packages/calango-cli/calango_cli/templates/alembic/env.py.jinja` | Wire `target_metadata` |
| `packages/calango-cli/calango_cli/templates/app/seeds/*` | Seeds scaffold |
| `packages/calango-cli/calango_cli/commands/new.py` | Register seed templates |
| `packages/calango-cli/tests/test_new_command.py` | Template assertions |
| `CLAUDE.md`, `README.md`, `ROADMAP.md` | Docs |

---

## Task 1: Canonical `Base` in calango-core

**Files:**
- Create: `packages/calango-core/calango/db/__init__.py`
- Test: `packages/calango-core/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/calango-core/tests/test_db.py
from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from calango.db import Base


def test_concrete_model_inherits_id_and_timestamps():
    class Widget(Base):
        __tablename__ = "widgets"
        name: Mapped[str] = mapped_column()

    cols = {c.name for c in Widget.__table__.columns}
    assert {"id", "created_at", "updated_at", "name"} <= cols


def test_models_share_one_metadata():
    class Gadget(Base):
        __tablename__ = "gadgets"

    assert "gadgets" in Base.metadata.tables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/calango-core/tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'calango.db'`

- [ ] **Step 3: Write minimal implementation**

```python
# packages/calango-core/calango/db/__init__.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ["Base", "import_models"]


class Base(DeclarativeBase):
    """Canonical declarative base. Every application model inherits this so a
    single ``Base.metadata`` sees all models for Alembic autogenerate."""

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
```

Note: `import_models` is added in Task 2; `__all__` already lists it so the import in `env.py` is stable. (The columns-on-declarative-root pattern is verified working on this SQLAlchemy version — a concrete subclass inherits all three columns and registers on `Base.metadata`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/calango-core/tests/test_db.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/calango-core/calango/db/__init__.py packages/calango-core/tests/test_db.py
git commit -m "feat(core): add canonical calango.db.Base with id + timestamps"
```

---

## Task 2: `import_models()` auto-discovery

**Files:**
- Modify: `packages/calango-core/calango/db/__init__.py`
- Test: `packages/calango-core/tests/test_db.py`

- [ ] **Step 1: Write the failing test** (append to test_db.py)

```python
def test_import_models_registers_context_models(tmp_path, monkeypatch):
    import sys

    # Build a fake project package: pkg/shop/models/order.py
    pkg = tmp_path / "demo_app" / "contexts" / "shop" / "models"
    pkg.mkdir(parents=True)
    for p in [tmp_path / "demo_app", tmp_path / "demo_app" / "contexts",
              tmp_path / "demo_app" / "contexts" / "shop", pkg]:
        (p / "__init__.py").write_text("")
    (pkg / "order.py").write_text(
        "from sqlalchemy.orm import Mapped, mapped_column\n"
        "from calango.db import Base\n"
        "class Order(Base):\n"
        "    __tablename__ = 'discovery_orders'\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    from calango.db import import_models

    import_models("demo_app.contexts")
    assert "discovery_orders" in Base.metadata.tables


def test_import_models_absent_package_is_noop():
    from calango.db import import_models

    import_models("nonexistent.package.path")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/calango-core/tests/test_db.py -k import_models -v`
Expected: FAIL — `ImportError: cannot import name 'import_models'`

- [ ] **Step 3: Write minimal implementation** (add to `calango/db/__init__.py`)

```python
import importlib
import pkgutil


def import_models(package: str = "app.contexts") -> None:
    """Import every ``models`` submodule under ``package`` so each model class
    registers on ``Base.metadata``. Safe to call when the package is absent."""
    try:
        root = importlib.import_module(package)
    except ModuleNotFoundError:
        return
    for ctx in pkgutil.iter_modules(root.__path__):
        models_pkg_name = f"{package}.{ctx.name}.models"
        try:
            models_pkg = importlib.import_module(models_pkg_name)
        except ModuleNotFoundError:
            continue
        for sub in pkgutil.iter_modules(models_pkg.__path__):
            importlib.import_module(f"{models_pkg_name}.{sub.name}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/calango-core/tests/test_db.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/calango-core/calango/db/__init__.py packages/calango-core/tests/test_db.py
git commit -m "feat(core): add import_models() for Alembic autogenerate discovery"
```

---

## Task 3: Bind `BaseRepository[T: Base]`, drop ty-ignores

**Files:**
- Modify: `packages/calango-core/calango/repository/__init__.py`
- Modify: `packages/calango-core/tests/test_repository.py`, `packages/calango-core/tests/test_service.py`

- [ ] **Step 1: Update test models to the canonical Base**

In `tests/test_repository.py` and `tests/test_service.py`, replace the local
`class Base(DeclarativeBase): pass` + `class Item(Base)` block with:

```python
import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from calango.db import Base


class Item(Base):
    __tablename__ = "items"
    name: Mapped[str] = mapped_column(String(100))
```

Remove the now-redundant local `id` column (inherited from Base as `uuid.UUID`).
Update `ItemCreate` so `id` is `uuid.UUID` (was `str`). In `test_service.py`,
delete the `# ty: ignore[invalid-argument-type]` comment on the
`service.repository.get(item.id)` line (now `item.id` is `UUID`, matching `get`).
Remove unused `DeclarativeBase` / `uuid4` imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/calango-core/tests/test_repository.py packages/calango-core/tests/test_service.py -v`
Expected: FAIL — `BaseRepository` is still `[T]` (unbound); `self.model.id` typing
and the UUID id change surface. (Runtime may pass; the bind is Step 3.)

- [ ] **Step 3: Bind the repository to Base and drop the ty-ignore**

In `packages/calango-core/calango/repository/__init__.py`:
- Add import: `from calango.db import Base`
- Change `class BaseRepository[T]:` to `class BaseRepository[T: Base]:`
- Delete the two comment lines and the `# ty: ignore[unresolved-attribute]` on the
  `.where(self.model.id == record_id)` line in `get_for_update` (now `id` resolves
  via the `Base` bound). Keep `import builtins` and the `builtins.list[T]` return.

- [ ] **Step 4: Run tests + type check to verify**

Run: `uv run pytest packages/calango-core/ -q && uv run ty check packages/`
Expected: tests PASS; ty `All checks passed!` (no ignore needed for `self.model.id`)

- [ ] **Step 5: Commit**

```bash
git add packages/calango-core/calango/repository/__init__.py packages/calango-core/tests/test_repository.py packages/calango-core/tests/test_service.py
git commit -m "refactor(core): bind BaseRepository[T: Base], drop two ty-ignores"
```

---

## Task 4: `calango db` group — alembic wrappers

**Files:**
- Create: `packages/calango-cli/calango_cli/commands/db.py`
- Modify: `packages/calango-cli/calango_cli/main.py`
- Test: `packages/calango-cli/tests/test_db_command.py`

- [ ] **Step 1: Write the failing tests**

```python
# packages/calango-cli/tests/test_db_command.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from calango_cli.main import app

runner = CliRunner()


def _project(tmp_path: Path) -> Path:
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    (tmp_path / "app").mkdir()
    return tmp_path


def test_db_help_exits_0():
    assert runner.invoke(app, ["db", "--help"]).exit_code == 0


def test_db_migrate_runs_upgrade_head(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["db", "migrate", "--path", str(tmp_path)])
    assert result.exit_code == 0
    argv = run.call_args.args[0]
    assert argv[-2:] == ["upgrade", "head"]


def test_db_rollback_default_one_step(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        runner.invoke(app, ["db", "rollback", "--path", str(tmp_path)])
    assert run.call_args.args[0][-2:] == ["downgrade", "-1"]


def test_db_revision_passes_message(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        runner.invoke(app, ["db", "revision", "-m", "add orders", "--path", str(tmp_path)])
    argv = run.call_args.args[0]
    assert "--autogenerate" in argv and "add orders" in argv


def test_db_migrate_not_a_project_exits_1(tmp_path):
    result = runner.invoke(app, ["db", "migrate", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_db_migrate_propagates_alembic_failure(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1)
        result = runner.invoke(app, ["db", "migrate", "--path", str(tmp_path)])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/calango-cli/tests/test_db_command.py -v`
Expected: FAIL — `No such command 'db'`

- [ ] **Step 3: Write the command group**

```python
# packages/calango-cli/calango_cli/commands/db.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from calango_cli.ui import print_error, print_info, print_success

db_app = typer.Typer(help="Database migrations and seeds.")


def _require_project(path: Path) -> Path:
    project = path.resolve()
    if not (project / "alembic.ini").exists():
        print_error(
            f"'{project}' is not a Calango project.",
            hint="No alembic.ini found. Run inside a generated project.",
        )
        raise typer.Exit(1)
    return project


def _alembic(project: Path, *args: str) -> int:
    uv = shutil.which("uv")
    if uv is None:
        print_error("uv not found.", hint="Install uv: https://docs.astral.sh/uv/")
        raise typer.Exit(1)
    return subprocess.run(  # noqa: S603 — resolved path, fixed args
        [uv, "run", "alembic", *args], cwd=project
    ).returncode


@db_app.command("revision")
def revision(
    message: str = typer.Option(..., "-m", "--message", help="Migration message"),
    path: Path = typer.Option(Path("."), "--path", help="Project root"),
) -> None:
    """Autogenerate a migration from model changes."""
    project = _require_project(path)
    print_info("Creating migration", {"message": message})
    code = _alembic(project, "revision", "--autogenerate", "-m", message)
    if code == 0:
        print_success("Migration created.", detail="Review it, then: calango db migrate")
    raise typer.Exit(code)


@db_app.command("migrate")
def migrate(path: Path = typer.Option(Path("."), "--path", help="Project root")) -> None:
    """Apply all pending migrations (alembic upgrade head)."""
    project = _require_project(path)
    code = _alembic(project, "upgrade", "head")
    if code == 0:
        print_success("Database is up to date.")
    raise typer.Exit(code)


@db_app.command("rollback")
def rollback(
    step: int = typer.Option(1, "--step", help="How many migrations to revert"),
    path: Path = typer.Option(Path("."), "--path", help="Project root"),
) -> None:
    """Revert the last N migrations (default 1)."""
    project = _require_project(path)
    code = _alembic(project, "downgrade", f"-{step}")
    if code == 0:
        print_success(f"Rolled back {step} migration(s).")
    raise typer.Exit(code)
```

Add to `packages/calango-cli/calango_cli/main.py`:

```python
from calango_cli.commands.db import db_app
# ...
app.add_typer(db_app, name="db")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/calango-cli/tests/test_db_command.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/calango-cli/calango_cli/commands/db.py packages/calango-cli/calango_cli/main.py packages/calango-cli/tests/test_db_command.py
git commit -m "feat(cli): add calango db revision/migrate/rollback (alembic wrappers)"
```

---

## Task 5: `calango db seed`

**Files:**
- Modify: `packages/calango-cli/calango_cli/commands/db.py`
- Test: `packages/calango-cli/tests/test_db_command.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_discover_seeds_sorts_by_name(tmp_path):
    from calango_cli.commands.db import _discover_seeds

    seeds = tmp_path / "app" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "__init__.py").write_text("")
    (seeds / "002_b.py").write_text("async def seed(session): ...\n")
    (seeds / "001_a.py").write_text("async def seed(session): ...\n")
    names = [p.name for p in _discover_seeds(tmp_path)]
    assert names == ["001_a.py", "002_b.py"]


def test_db_seed_without_seeds_dir_exits_1(tmp_path):
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    (tmp_path / "app").mkdir()
    result = runner.invoke(app, ["db", "seed", "--path", str(tmp_path)])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/calango-cli/tests/test_db_command.py -k seed -v`
Expected: FAIL — `cannot import name '_discover_seeds'` / no `seed` command

- [ ] **Step 3: Implement seed discovery + command** (add to `db.py`)

```python
import asyncio
import importlib.util


def _discover_seeds(project: Path) -> list[Path]:
    seeds_dir = project / "app" / "seeds"
    if not seeds_dir.exists():
        return []
    return sorted(p for p in seeds_dir.glob("[0-9]*_*.py") if p.is_file())


async def _run_seeds(project: Path, seeds: list[Path]) -> None:
    import sys

    sys.path.insert(0, str(project))
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    config_mod = importlib.import_module("app.core.config")
    settings = config_mod.Settings()
    engine = create_async_engine(settings.database.URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        for seed_file in seeds:
            spec = importlib.util.spec_from_file_location(seed_file.stem, seed_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            async with maker() as session, session.begin():
                await module.seed(session)
    finally:
        await engine.dispose()


@db_app.command("seed")
def seed(path: Path = typer.Option(Path("."), "--path", help="Project root")) -> None:
    """Run app/seeds/ modules in filename order, each in its own transaction."""
    project = path.resolve()
    if not (project / "app" / "seeds").exists():
        print_error(
            "No app/seeds/ directory found.",
            hint="Add ordered seed modules like app/seeds/001_example.py.",
        )
        raise typer.Exit(1)
    seeds = _discover_seeds(project)
    print_info("Seeding", {"modules": str(len(seeds))})
    asyncio.run(_run_seeds(project, seeds))
    print_success(f"Ran {len(seeds)} seed module(s).")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/calango-cli/tests/test_db_command.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/calango-cli/calango_cli/commands/db.py packages/calango-cli/tests/test_db_command.py
git commit -m "feat(cli): add calango db seed (ordered app/seeds modules)"
```

---

## Task 6: Template — lean model + wired env.py

**Files:**
- Modify: `packages/calango-cli/calango_cli/templates/resource/model.py.jinja`
- Modify: `packages/calango-cli/calango_cli/templates/alembic/env.py.jinja`
- Test: `packages/calango-cli/tests/test_generate_command.py`, `tests/test_new_command.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_generate_command.py` add:

```python
def test_generate_model_inherits_calango_base(tmp_path):
    _make_project(tmp_path)
    runner.invoke(app, ["generate", "resource", "Shop.Order", "--path", str(tmp_path)])
    content = (tmp_path / "app" / "contexts" / "shop" / "models" / "order.py").read_text()
    assert "from calango.db import Base" in content
    assert "class Base(DeclarativeBase)" not in content
```

In `tests/test_new_command.py` add:

```python
def test_new_alembic_env_wires_target_metadata(tmp_path):
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    env = (tmp_path / "my-api" / "alembic" / "env.py").read_text()
    assert "from calango.db import Base, import_models" in env
    assert "target_metadata = Base.metadata" in env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/calango-cli/tests/test_generate_command.py -k calango_base packages/calango-cli/tests/test_new_command.py -k target_metadata -v`
Expected: FAIL — model still defines local Base; env still has `target_metadata = None`

- [ ] **Step 3: Rewrite the templates**

`templates/resource/model.py.jinja`:

```jinja
from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from calango.db import Base


class {{ resource_name }}(Base):
    """SQLAlchemy model for {{ resource_name }}. Add business fields here.

    id, created_at and updated_at are inherited from calango.db.Base.
    """

    __tablename__ = "{{ resource_plural }}"

    # TODO: add your fields here
    # name: Mapped[str] = mapped_column(String(255))
```

In `templates/alembic/env.py.jinja` replace line 5 and the `target_metadata` line:

```jinja
from app.core.config import Settings
from calango.db import Base, import_models
```

```jinja
import_models("app.contexts")
target_metadata = Base.metadata
```

(Replace `target_metadata = None  # Set to Base.metadata after defining models`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/calango-cli/tests/test_generate_command.py packages/calango-cli/tests/test_new_command.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add packages/calango-cli/calango_cli/templates/resource/model.py.jinja packages/calango-cli/calango_cli/templates/alembic/env.py.jinja packages/calango-cli/tests/test_generate_command.py packages/calango-cli/tests/test_new_command.py
git commit -m "feat(cli/templates): inherit calango.db.Base, wire alembic target_metadata"
```

---

## Task 7: Template — seeds scaffold

**Files:**
- Create: `packages/calango-cli/calango_cli/templates/app/seeds/__init__.py.jinja`
- Create: `packages/calango-cli/calango_cli/templates/app/seeds/001_example.py.jinja`
- Modify: `packages/calango-cli/calango_cli/commands/new.py`
- Test: `packages/calango-cli/tests/test_new_command.py`

- [ ] **Step 1: Write the failing test** (append to test_new_command.py)

```python
def test_new_creates_seeds_example(tmp_path):
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    example = tmp_path / "my-api" / "app" / "seeds" / "001_example.py"
    assert example.exists()
    assert "async def seed(session" in example.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/calango-cli/tests/test_new_command.py -k seeds_example -v`
Expected: FAIL — file does not exist

- [ ] **Step 3: Create the templates + register**

`templates/app/seeds/__init__.py.jinja`: empty file (single newline).

`templates/app/seeds/001_example.py.jinja`:

```jinja
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def seed(session: AsyncSession) -> None:
    """Seed example data. Runs inside a transaction; make it idempotent.

    Example:
        from app.contexts.shop import OrderRepository
        repo = OrderRepository(session)
        ...
    """
    # TODO: insert your seed data here
```

In `packages/calango-cli/calango_cli/commands/new.py`, add to `_TEMPLATE_FILES`
(after the `security/opengrep/...` entry):

```python
    ("app/seeds/__init__.py.jinja", "app/seeds/__init__.py"),
    ("app/seeds/001_example.py.jinja", "app/seeds/001_example.py"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/calango-cli/tests/test_new_command.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/calango-cli/calango_cli/templates/app/seeds/ packages/calango-cli/calango_cli/commands/new.py packages/calango-cli/tests/test_new_command.py
git commit -m "feat(cli/new): scaffold app/seeds/ with an example seed module"
```

---

## Task 8: End-to-end verification + docs

**Files:**
- Modify: `ROADMAP.md`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: Full quality loop**

Run:
```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check packages/ && uv run pytest packages/ -q
```
Expected: all green, no ty-ignores remaining for `self.model.id`.

- [ ] **Step 2: Real end-to-end migration run**

Run:
```bash
rm -rf /tmp/db-demo
uv run calango new db-demo --path /tmp
uv run calango generate resource Shop.Order --path /tmp/db-demo
cd /tmp/db-demo
# point DB at a local sqlite for the smoke test:
DATABASE__URL="sqlite+aiosqlite:///./demo.db" uv run --with calango-core --with aiosqlite calango db revision -m "add orders" --path .
ls alembic/versions/*.py     # a migration file mentioning 'orders'
```
Expected: a migration is generated containing the `orders` table (proves
`import_models` + `target_metadata` work across contexts). If `calango-core`
is not yet published, run from the monorepo so the local package resolves.

- [ ] **Step 3: Update docs**

In `ROADMAP.md`: change `### Phase 5: calango-cli — db commands 🟡 Next` to `✅ Done`.
In `README.md` component status: change `| \`calango-cli\` — \`calango db migrate\` | 🟡 Next |`
to `| \`calango-cli\` — \`calango db\` (migrate/revision/seed) | ✅ Done |`; flip the
M2 milestone row to `🟢 Done` only if Phase 5 completes M2.
In `CLAUDE.md`: under the implemented list add
`- [x] \`calango-cli\`: \`calango db\` — revision/migrate/rollback/seed + canonical \`calango.db.Base\``;
add a short "Models inherit \`calango.db.Base\`" note to the Naming/conventions section.

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md README.md CLAUDE.md
git commit -m "docs: mark Phase 5 (db commands) done; document canonical Base"
```

- [ ] **Step 5: Finish the branch**

Use superpowers:finishing-a-development-branch (verify tests, present merge options).

---

## Self-review notes

- **Spec coverage:** Base (T1), import_models/Approach A (T2), bound repository + ty-ignore removal (T3), revision/migrate/rollback (T4), seed (T5), model+env templates (T6), seeds scaffold (T7), identity untouched (no task — intentional), suggest-indexes deferred (out of scope), docs (T8). All covered.
- **Type consistency:** `Base` (calango.db), `BaseRepository[T: Base]`, `import_models(package)`, `_discover_seeds(project)`, `_run_seeds(project, seeds)`, `_alembic(project, *args)`, `db_app` — names consistent across tasks.
- **De-risked:** the columns-on-declarative-root pattern (Task 1) was verified against this SQLAlchemy version before handoff — a concrete subclass inherits id/created_at/updated_at and registers on `Base.metadata`.
