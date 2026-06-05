import re
from pathlib import Path

import typer
from jinja2 import Environment, PackageLoader, select_autoescape

from calango_cli.ui import (
    ask,
    is_interactive,
    print_error,
    print_file_tree,
    print_success,
)

app = typer.Typer()


def _render_resource_templates(project_dir: Path, context: dict) -> list[str]:
    """Render resource templates into the project. Returns list of created file paths."""
    env = Environment(
        loader=PackageLoader("calango_cli", "templates"),
        keep_trailing_newline=True,
        autoescape=select_autoescape(enabled_extensions=("html",), default=False),
    )
    snake = context["resource_snake"]
    files = [
        ("resource/model.py.jinja", f"app/models/{snake}.py"),
        ("resource/schemas.py.jinja", f"app/schemas/{snake}.py"),
        ("resource/repository.py.jinja", f"app/repositories/{snake}.py"),
        ("resource/service.py.jinja", f"app/services/{snake}.py"),
        ("resource/router.py.jinja", f"app/routers/{snake}.py"),
        ("resource/test_service.py.jinja", f"tests/unit/test_{snake}_service.py"),
        ("resource/test_router.py.jinja", f"tests/integration/test_{snake}_router.py"),
        ("resource/factory.py.jinja", f"tests/factories/{snake}_factory.py"),
    ]
    created = []
    for template_name, output_path in files:
        template = env.get_template(template_name)
        content = template.render(**context)
        out = project_dir / output_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
        created.append(output_path)
    return created


def _to_snake_case(name: str) -> str:
    """Convert PascalCase or CamelCase to snake_case. E.g. 'ProductItem' → 'product_item'."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def _to_plural(name: str) -> str:
    """Simple pluralization for router prefix. 'order' → 'orders', 'category' → 'categories'."""
    if name.endswith("y"):
        return name[:-1] + "ies"
    return name + "s"


@app.command("resource")
def resource(
    name: str | None = typer.Argument(None, help="Resource name in PascalCase (e.g. Order, ProductItem)"),
    path: Path = typer.Option(Path("."), "--path", help="Project root directory"),
) -> None:
    """Generate a complete resource: model + schema + repo + service + router + tests + factory."""
    if name is None:
        if not is_interactive():
            print_error(
                "Missing argument 'NAME'.",
                hint="Run interactively: calango generate resource",
            )
            raise typer.Exit(1)
        name = ask("Resource name (PascalCase, e.g. Order)")

    if not name[0].isupper():
        print_error(
            f"Resource name must be PascalCase (e.g. 'Order', not '{name}').",
        )
        raise typer.Exit(1)

    project_dir = path.resolve()
    if not (project_dir / "app").exists():
        print_error(
            f"'{project_dir}' does not look like a Calango project.",
            hint="Missing app/ directory.",
        )
        raise typer.Exit(1)

    snake = _to_snake_case(name)
    plural = _to_plural(snake)
    context = {
        "resource_name": name,
        "resource_snake": snake,
        "resource_plural": plural,
    }
    created = _render_resource_templates(project_dir, context)
    print_file_tree(name, created)
    print_success(f"Resource generated — {name} ({len(created)} files)")
