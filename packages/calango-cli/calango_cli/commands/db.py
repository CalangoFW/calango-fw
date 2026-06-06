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
