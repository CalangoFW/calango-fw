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


def _parse_resource_arg(arg: str) -> tuple[str, str]:
    """Parse 'Context.Resource' → (context_name, resource_name). Both must be PascalCase."""
    if "." not in arg:
        raise ValueError("missing_dot")
    parts = arg.split(".", 1)
    context_name, resource_name = parts[0], parts[1]
    if not context_name or not context_name[0].isupper():
        raise ValueError("bad_context")
    if not resource_name or not resource_name[0].isupper():
        raise ValueError("bad_resource")
    return context_name, resource_name


def _render_resource_templates(
    project_dir: Path,
    env: Environment,
    context: dict,
) -> list[str]:
    """Render resource templates into the project. Returns list of created file paths."""
    ctx = context["context_snake"]
    res = context["resource_snake"]
    files = [
        ("resource/model.py.jinja", f"app/contexts/{ctx}/models/{res}.py"),
        ("resource/schemas.py.jinja", f"app/contexts/{ctx}/schemas/{res}.py"),
        ("resource/repository.py.jinja", f"app/contexts/{ctx}/repositories/{res}.py"),
        ("resource/service.py.jinja", f"app/contexts/{ctx}/services/{res}.py"),
        ("resource/router.py.jinja", f"app/routers/{res}.py"),
        ("resource/test_service.py.jinja", f"tests/unit/{ctx}/test_{res}_service.py"),
        ("resource/test_router.py.jinja", f"tests/integration/{ctx}/test_{res}_router.py"),
        ("resource/factory.py.jinja", f"tests/factories/{res}_factory.py"),
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


def _update_context_init(
    project_dir: Path,
    env: Environment,
    context_snake: str,
    context_name: str,
    resource_name: str,
    resource_snake: str,
) -> str:
    """Create or re-render the context __init__.py. Returns the output path."""
    init_path = project_dir / "app" / "contexts" / context_snake / "__init__.py"

    # Collect existing resources by parsing the init file (if it exists)
    existing = []
    if init_path.exists():
        content = init_path.read_text()
        # Extract resource snake names from lines like:
        # "from app.contexts.<ctx>.services.<snake> import <Name>Service"
        svc_pattern = (
            rf"from app\.contexts\.{re.escape(context_snake)}"
            rf"\.services\.(\w+) import (\w+)Service"
        )
        for snake, name in re.findall(svc_pattern, content):
            existing.append({"snake": snake, "name": name})

    # Add new resource (dedup by snake name)
    new_resource = {"snake": resource_snake, "name": resource_name}
    if not any(r["snake"] == resource_snake for r in existing):
        existing.append(new_resource)

    # Sort alphabetically by name
    resources = sorted(existing, key=lambda r: r["name"])

    # Render and write
    template = env.get_template("resource/context_init.py.jinja")
    rendered = template.render(
        context_name=context_name,
        context_snake=context_snake,
        resources=resources,
    )
    init_path.parent.mkdir(parents=True, exist_ok=True)
    init_path.write_text(rendered)
    return f"app/contexts/{context_snake}/__init__.py"


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
    name: str | None = typer.Argument(
        None,
        help="Resource in Context.Resource format, e.g. Shop.Order",
    ),
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
        name = ask("Resource (format: Context.Resource, e.g. Shop.Order)")

    # Parse and validate Context.Resource notation
    try:
        context_name, resource_name = _parse_resource_arg(name)
    except ValueError as exc:
        code = str(exc)
        if code == "missing_dot":
            print_error(
                "Resource name must use Context.Resource format.",
                hint="Example: calango generate resource Shop.Order",
            )
        elif code == "bad_context":
            print_error(
                "Context name must be PascalCase.",
                hint="Example: calango generate resource Shop.Order",
            )
        else:  # bad_resource
            print_error(
                "Resource name must be PascalCase.",
                hint="Example: calango generate resource Shop.Order",
            )
        raise typer.Exit(1) from exc

    project_dir = path.resolve()
    if not (project_dir / "app").exists():
        print_error(
            f"'{project_dir}' does not look like a Calango project.",
            hint="Missing app/ directory.",
        )
        raise typer.Exit(1)

    context_snake = _to_snake_case(context_name)
    resource_snake = _to_snake_case(resource_name)
    plural = _to_plural(resource_snake)

    env = Environment(
        loader=PackageLoader("calango_cli", "templates"),
        keep_trailing_newline=True,
        autoescape=select_autoescape(enabled_extensions=("html",), default=False),
    )

    template_context = {
        "context_name": context_name,
        "context_snake": context_snake,
        "resource_name": resource_name,
        "resource_snake": resource_snake,
        "resource_plural": plural,
    }

    created = _render_resource_templates(project_dir, env, template_context)
    init_path = _update_context_init(
        project_dir,
        env,
        context_snake,
        context_name,
        resource_name,
        resource_snake,
    )
    created.append(init_path)

    print_file_tree(f"{context_name}.{resource_name}", created)
    print_success(f"Resource generated — {context_name}.{resource_name} ({len(created)} files)")
