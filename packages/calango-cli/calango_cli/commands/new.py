from pathlib import Path

import typer
from jinja2 import Environment, PackageLoader, select_autoescape
from rich.console import Console

console = Console()

_TEMPLATE_FILES = [
    ("app/__init__.py.jinja", "app/__init__.py"),
    ("app/main.py.jinja", "app/main.py"),
    ("app/core/__init__.py.jinja", "app/core/__init__.py"),
    ("app/core/config.py.jinja", "app/core/config.py"),
    ("tests/__init__.py.jinja", "tests/__init__.py"),
    ("tests/conftest.py.jinja", "tests/conftest.py"),
    ("alembic/env.py.jinja", "alembic/env.py"),
    ("alembic.ini.jinja", "alembic.ini"),
]


def _render_templates(project_dir: Path, context: dict) -> None:
    env = Environment(
        loader=PackageLoader("calango_cli", "templates"),
        keep_trailing_newline=True,
        autoescape=select_autoescape(enabled_extensions=("html",), default=False),
    )
    for template_name, output_path in _TEMPLATE_FILES:
        template = env.get_template(template_name)
        content = template.render(**context)
        out = project_dir / output_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)


def new(
    name: str = typer.Argument(..., help="Project name"),
    path: Path = typer.Option(Path("."), "--path", help="Parent directory"),
    db: str = typer.Option("postgres", "--db", help="Database backend"),
    agents: bool = typer.Option(False, "--agents", help="Enable agents plugin"),
    ci: str = typer.Option("github", "--ci", help="CI provider"),
) -> None:
    """Create a new Calango project."""
    project_dir = path / name
    if project_dir.exists():
        console.print(f"[red]Error:[/red] Directory '{project_dir}' already exists.")
        raise typer.Exit(1)

    project_dir.mkdir(parents=True)
    _render_templates(
        project_dir,
        {"project_name": name, "db": db, "agents": agents, "ci": ci},
    )
    console.print(f"[green]✓[/green]  Created project: {name}")
