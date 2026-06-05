from pathlib import Path

import typer
from jinja2 import Environment, PackageLoader, select_autoescape

from calango_cli.ui import (
    ask,
    ask_choice,
    ask_confirm,
    is_interactive,
    print_banner,
    print_error,
    print_file_tree,
    print_info,
    print_success,
)

_TEMPLATE_FILES = [
    ("app/__init__.py.jinja", "app/__init__.py"),
    ("app/main.py.jinja", "app/main.py"),
    ("app/core/__init__.py.jinja", "app/core/__init__.py"),
    ("app/core/config.py.jinja", "app/core/config.py"),
    ("tests/__init__.py.jinja", "tests/__init__.py"),
    ("tests/conftest.py.jinja", "tests/conftest.py"),
    ("alembic/env.py.jinja", "alembic/env.py"),
    ("alembic/versions/.gitkeep.jinja", "alembic/versions/.gitkeep"),
    ("alembic.ini.jinja", "alembic.ini"),
    ("Dockerfile.jinja", "Dockerfile"),
    ("compose.yml.jinja", "compose.yml"),
    ("github/workflows/ci.yml.jinja", ".github/workflows/ci.yml"),
    ("github/workflows/cd.yml.jinja", ".github/workflows/cd.yml"),
    ("github/pull_request_template.md.jinja", ".github/pull_request_template.md"),
    ("gitignore.jinja", ".gitignore"),
    ("pyproject.toml.jinja", "pyproject.toml"),
    ("env.example.jinja", ".env.example"),
    ("CLAUDE.md.jinja", "CLAUDE.md"),
    ("cursorrules.jinja", ".cursorrules"),
    ("CHANGELOG.md.jinja", "CHANGELOG.md"),
    ("SECURITY.md.jinja", "SECURITY.md"),
]

_SUPPORTED_DB = {"postgres"}
_SUPPORTED_CI = {"github"}


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
    name: str | None = typer.Argument(None, help="Project name"),
    path: Path = typer.Option(Path("."), "--path", help="Parent directory"),
    db: str = typer.Option("postgres", "--db", help="Database backend"),
    agents: bool = typer.Option(False, "--agents", help="Enable agents plugin"),
    ci: str = typer.Option("github", "--ci", help="CI provider"),
) -> None:
    """Create a new Calango project."""
    if name is None:
        if not is_interactive():
            print_error(
                "Missing argument 'NAME'.",
                hint="Run interactively: calango new",
            )
            raise typer.Exit(1)
        print_banner("new project")
        name = ask("Project name")
        db = ask_choice(
            "Database",
            ["postgres", "mongo"],
            default="postgres",
            disabled={"mongo": "coming soon"},
        )
        agents = ask_confirm("Enable agents plugin?", default=False)
        ci = ask_choice(
            "CI provider",
            ["github", "gitlab"],
            default="github",
            disabled={"gitlab": "coming soon"},
        )
    else:
        print_info(f"Creating project — {name}", {
            "db": db,
            "ci": ci,
            "agents": "enabled" if agents else "disabled",
        })

    project_dir = path / name

    if project_dir.exists():
        print_error(
            f"Directory '{project_dir}' already exists.",
            hint="Choose a different name or remove the existing directory.",
        )
        raise typer.Exit(1)

    if db not in _SUPPORTED_DB:
        print_error(
            f"--db={db!r} is not supported.",
            hint=f"Supported: {', '.join(_SUPPORTED_DB)}",
        )
        raise typer.Exit(1)

    if ci not in _SUPPORTED_CI:
        print_error(
            f"--ci={ci!r} is not supported.",
            hint=f"Supported: {', '.join(_SUPPORTED_CI)}",
        )
        raise typer.Exit(1)

    project_dir.mkdir(parents=True)
    _render_templates(
        project_dir,
        {"project_name": name, "db": db, "agents": agents, "ci": ci},
    )

    created = [output_path for _, output_path in _TEMPLATE_FILES]
    display = created[:5] + ([f"+ {len(created) - 5} more files"] if len(created) > 5 else [])
    print_file_tree(name, display)
    print_success(
        f"Project created — {name} ({len(created)} files)",
        detail=f"Next: cd {name} && calango db migrate",
    )
