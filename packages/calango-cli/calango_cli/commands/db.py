from __future__ import annotations

import asyncio
import importlib.util
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


def _current_revisions(project: Path) -> tuple[int, tuple[tuple[str, tuple[str, ...]], ...]]:
    uv = shutil.which("uv")
    if uv is None:
        print_error("uv not found.", hint="Install uv: https://docs.astral.sh/uv/")
        raise typer.Exit(1)
    result = subprocess.run(  # noqa: S603 — resolved path, fixed args
        [uv, "run", "alembic", "current", "--verbose"],
        cwd=project,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return result.returncode, ()
    revisions: list[tuple[str, tuple[str, ...]]] = []
    for line in result.stdout.splitlines():
        if line.startswith("Rev: "):
            revisions.append((line.removeprefix("Rev: ").split()[0], ()))
        elif line.startswith("Merges: ") and revisions:
            parents = tuple(
                sorted(part.strip() for part in line.removeprefix("Merges: ").split(","))
            )
            revision, _ = revisions[-1]
            revisions[-1] = (revision, parents)
    return 0, tuple(sorted(revisions))


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
    """Apply all pending migrations across every Alembic head."""
    project = _require_project(path)
    code = _alembic(project, "upgrade", "heads")
    if code == 0:
        print_success("Database is up to date.")
    raise typer.Exit(code)


@db_app.command("rollback")
def rollback(
    step: int = typer.Option(
        1,
        "--step",
        min=1,
        help="How many migrations to revert on every current branch",
    ),
    path: Path = typer.Option(Path("."), "--path", help="Project root"),
) -> None:
    """Revert the last N migrations on every current Alembic branch."""
    project = _require_project(path)
    remaining = step
    code = 0
    while code == 0 and remaining:
        code, revisions = _current_revisions(project)
        if code != 0:
            break
        if not revisions:
            print_error("No migrations remain to roll back.")
            code = 1
            break

        for revision, parents in revisions:
            target = f"{revision}@{parents[0]}" if len(parents) > 1 else f"{revision}@-1"
            code = _alembic(project, "downgrade", target)
            if code != 0:
                break
        remaining -= 1
    if code == 0:
        print_success(f"Rolled back {step} migration(s).")
    raise typer.Exit(code)


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
            if spec is None or spec.loader is None:
                continue
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
