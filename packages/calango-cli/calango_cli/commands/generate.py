import re
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


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
    # Template rendering will be added in subsequent tasks
    _ = plural  # used in templates
