import re
from pathlib import Path

import typer
from jinja2 import Environment, PackageLoader, select_autoescape
from rich.console import Console

app = typer.Typer()
console = Console()


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
    ]
    created = []
    for template_name, output_path in files:
        template = env.get_template(template_name)
        content = template.render(**context)
        out = project_dir / output_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
        created.append(output_path)
        console.print(f"  [dim]created[/dim] {output_path}")

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
    name: str = typer.Argument(..., help="Resource name in PascalCase (e.g. Order, ProductItem)"),
    path: Path = typer.Option(Path("."), "--path", help="Project root directory"),
) -> None:
    """Generate a complete resource: model + schema + repo + service + router + tests + factory."""
    if not name[0].isupper():
        console.print(
            f"[red]Error:[/red] Resource name must be PascalCase (e.g. 'Order', not '{name}')."
        )
        raise typer.Exit(1)

    project_dir = path.resolve()
    if not (project_dir / "app").exists():
        console.print(
            f"[red]Error:[/red] '{project_dir}' does not look like a Calango project "
            "(missing app/ directory)."
        )
        raise typer.Exit(1)

    snake = _to_snake_case(name)
    plural = _to_plural(snake)

    console.print(f"[green]✓[/green]  Generating resource: {name}")
    context = {
        "resource_name": name,
        "resource_snake": snake,
        "resource_plural": plural,
    }
    _render_resource_templates(project_dir, context)
    console.print(f"[green]✓[/green]  Resource {name} generated successfully.")
