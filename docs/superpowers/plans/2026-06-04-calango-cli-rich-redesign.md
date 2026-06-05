# Calango CLI — Rich + questionary Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Calango CLI with a branded terminal experience using Rich panels, file trees, and questionary interactive wizards, plus a shared `ui.py` module that all future commands can build on.

**Architecture:** All terminal output and interactive prompts are centralised in `calango_cli/ui.py` — command files import from there and never call `rich` or `questionary` directly. When a required argument is missing and stdin/stdout are a TTY, commands fall into an interactive wizard; flags always skip prompts (CI-safe).

**Tech Stack:** Python 3.12, Typer 0.13, Rich 13, questionary 2.0, Jinja2 3.1, pytest, unittest.mock

**Spec:** `docs/superpowers/specs/2026-06-04-calango-cli-rich-redesign.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `packages/calango-cli/pyproject.toml` | Modify | Add `questionary>=2.0` dependency |
| `packages/calango-cli/calango_cli/ui.py` | **Create** | All Rich + questionary primitives; never imported elsewhere without this file existing first |
| `packages/calango-cli/calango_cli/main.py` | Modify | Print branded banner when no subcommand is given |
| `packages/calango-cli/calango_cli/commands/new.py` | Modify | Rich output + interactive wizard; imports from `ui.py` |
| `packages/calango-cli/calango_cli/commands/generate.py` | Modify | Rich output + interactive wizard; imports from `ui.py` |
| `packages/calango-cli/tests/test_ui.py` | **Create** | Unit tests for every public function in `ui.py` |
| `packages/calango-cli/tests/test_new_command.py` | Modify | Add wizard path tests + no-name non-interactive exit-1 |
| `packages/calango-cli/tests/test_generate_command.py` | Modify | Add wizard path tests + no-name non-interactive exit-1 |
| `packages/calango-cli/CLAUDE.md` | **Create** | CLI authoring guide — how to write a new command |
| `CLAUDE.md` (root) | Modify | Add "CLI conventions" section referencing `ui.py` API |

---

## Task 1: Add questionary dependency

**Files:**
- Modify: `packages/calango-cli/pyproject.toml`

- [ ] **Step 1: Add questionary to dependencies**

Open `packages/calango-cli/pyproject.toml` and change the `dependencies` list from:

```toml
dependencies = [
    "typer>=0.13",
    "jinja2>=3.1",
    "rich>=13",
    "calango-core",
]
```

to:

```toml
dependencies = [
    "typer>=0.13",
    "jinja2>=3.1",
    "rich>=13",
    "questionary>=2.0",
    "calango-core",
]
```

- [ ] **Step 2: Sync the workspace**

```bash
cd /home/akio/Dev/calango_fw
uv sync
```

Expected: questionary and its dependency (prompt_toolkit) appear in the output. No errors.

- [ ] **Step 3: Verify questionary is importable**

```bash
uv run python -c "import questionary; print(questionary.__version__)"
```

Expected: prints a version string like `2.0.0`.

- [ ] **Step 4: Commit**

```bash
git add packages/calango-cli/pyproject.toml uv.lock
git commit -m "feat(cli): add questionary>=2.0 dependency"
```

---

## Task 2: Create `ui.py` — Rich output primitives

**Files:**
- Create: `packages/calango-cli/calango_cli/ui.py`
- Create: `packages/calango-cli/tests/test_ui.py`

- [ ] **Step 1: Write failing tests for output functions**

Create `packages/calango-cli/tests/test_ui.py`:

```python
from unittest.mock import patch

import pytest


def test_is_interactive_false_without_tty():
    from calango_cli import ui
    assert ui.is_interactive() is False


def test_print_banner_does_not_raise():
    from calango_cli import ui
    ui.print_banner()


def test_print_banner_with_subtitle_does_not_raise():
    from calango_cli import ui
    ui.print_banner("new project")


def test_print_success_does_not_raise():
    from calango_cli import ui
    ui.print_success("Operation complete")


def test_print_success_with_detail_does_not_raise():
    from calango_cli import ui
    ui.print_success("Operation complete", detail="Next: do something")


def test_print_error_does_not_raise():
    from calango_cli import ui
    ui.print_error("Something went wrong")


def test_print_error_with_hint_does_not_raise():
    from calango_cli import ui
    ui.print_error("Something went wrong", hint="Try: calango new")


def test_print_info_does_not_raise():
    from calango_cli import ui
    ui.print_info("Creating project — my-api", {"db": "postgres", "ci": "github"})


def test_print_file_tree_does_not_raise():
    from calango_cli import ui
    ui.print_file_tree("my-project", ["app/main.py", "compose.yml"])


def test_print_file_tree_single_file_does_not_raise():
    from calango_cli import ui
    ui.print_file_tree("my-project", ["app/main.py"])
```

- [ ] **Step 2: Run tests — confirm they all fail with ImportError**

```bash
cd /home/akio/Dev/calango_fw
uv run pytest packages/calango-cli/tests/test_ui.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'ui' from 'calango_cli'` or `ModuleNotFoundError`.

- [ ] **Step 3: Create `calango_cli/ui.py` with all output primitives**

Create `packages/calango-cli/calango_cli/ui.py`:

```python
from __future__ import annotations

import sys

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.tree import Tree

_THEME = Theme({
    "calango.primary": "#2CBD6B",
    "calango.primary.bright": "#3FC878",
    "calango.accent": "#E29A2E",
    "calango.danger": "#E5575C",
    "calango.muted": "#6A736E",
    "calango.text": "#A9B2AD",
})

_STYLE = questionary.Style([
    ("qmark", "fg:#2CBD6B bold"),
    ("question", "fg:#F1F4F2 bold"),
    ("answer", "fg:#2CBD6B bold"),
    ("pointer", "fg:#2CBD6B bold"),
    ("highlighted", "fg:#2CBD6B bold"),
    ("selected", "fg:#3FC878"),
    ("separator", "fg:#6A736E"),
    ("instruction", "fg:#6A736E"),
    ("text", "fg:#A9B2AD"),
    ("disabled", "fg:#6A736E italic"),
])

console = Console(theme=_THEME)


def is_interactive() -> bool:
    """Return True only when both stdin and stdout are connected to a real TTY."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def print_banner(subtitle: str = "") -> None:
    """Print the branded calango. header panel."""
    title = Text()
    title.append("calango", style="calango.primary bold")
    title.append(".", style="calango.accent bold")
    if subtitle:
        title.append(f"  {subtitle}", style="calango.muted")
    console.print(Panel(
        title,
        subtitle="The fast, friendly Python web framework",
        border_style="calango.primary",
        padding=(0, 1),
    ))


def print_success(message: str, *, detail: str | None = None) -> None:
    """Print a green checkmark success line with optional detail hint."""
    console.print(f"[calango.primary]✓[/calango.primary]  {message}")
    if detail:
        console.print(f"  [calango.muted]{detail}[/calango.muted]")


def print_error(message: str, *, hint: str | None = None) -> None:
    """Print a red cross error line with optional hint."""
    console.print(f"[calango.danger]✗[/calango.danger]  {message}")
    if hint:
        console.print(f"  [calango.muted]{hint}[/calango.muted]")


def print_info(label: str, fields: dict[str, str]) -> None:
    """Print a muted panel showing key/value fields before an operation starts."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="calango.muted")
    table.add_column()
    for key, value in fields.items():
        table.add_row(key, value)
    console.print(Panel(
        table,
        title=f"[calango.primary]⬡[/calango.primary]  {label}",
        border_style="calango.muted",
    ))


def print_file_tree(root: str, files: list[str]) -> None:
    """Print a Rich tree of created files under root."""
    tree = Tree(f"[calango.primary]●[/calango.primary] [bold]{root}/[/bold]")
    for path in files:
        tree.add(f"[calango.text]{path}[/calango.text]")
    console.print(tree)


def ask(question: str, *, default: str = "") -> str:
    """Prompt for a text answer. Must only be called after is_interactive() is True."""
    return questionary.text(
        f"› {question}",
        default=default,
        style=_STYLE,
    ).unsafe_ask()


def ask_choice(
    question: str,
    choices: list[str],
    *,
    default: str,
    disabled: dict[str, str] | None = None,
) -> str:
    """Prompt for a choice. Pass disabled={choice: reason} to grey-out unavailable options."""
    qchoices = []
    for c in choices:
        if disabled and c in disabled:
            qchoices.append(questionary.Choice(
                title=f"{c}  ({disabled[c]})",
                value=c,
                disabled=disabled[c],
            ))
        else:
            qchoices.append(questionary.Choice(title=c, value=c))
    return questionary.select(
        f"› {question}",
        choices=qchoices,
        default=default,
        style=_STYLE,
    ).unsafe_ask()


def ask_confirm(question: str, *, default: bool = True) -> bool:
    """Prompt for a yes/no confirmation."""
    return questionary.confirm(
        f"› {question}",
        default=default,
        style=_STYLE,
    ).unsafe_ask()
```

- [ ] **Step 4: Run the output-function tests — confirm they pass**

```bash
uv run pytest packages/calango-cli/tests/test_ui.py -v 2>&1 | head -40
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/calango-cli/calango_cli/ui.py packages/calango-cli/tests/test_ui.py
git commit -m "feat(cli/ui): create shared ui.py — Rich theme, console, output primitives"
```

---

## Task 3: Add questionary wrapper tests to `test_ui.py`

**Files:**
- Modify: `packages/calango-cli/tests/test_ui.py`

- [ ] **Step 1: Add questionary wrapper tests**

Append to `packages/calango-cli/tests/test_ui.py`:

```python
def test_ask_delegates_to_questionary_text():
    from calango_cli import ui
    with patch("calango_cli.ui.questionary") as mock_q:
        mock_q.text.return_value.unsafe_ask.return_value = "my-answer"
        mock_q.Style = questionary.Style  # keep real Style constructor
        result = ui.ask("Project name")
    assert result == "my-answer"
    mock_q.text.assert_called_once()


def test_ask_choice_delegates_to_questionary_select():
    from calango_cli import ui
    with patch("calango_cli.ui.questionary") as mock_q:
        mock_q.Choice.side_effect = lambda title, value, **kw: value
        mock_q.select.return_value.unsafe_ask.return_value = "postgres"
        result = ui.ask_choice("Database", ["postgres", "mongo"], default="postgres")
    assert result == "postgres"
    mock_q.select.assert_called_once()


def test_ask_choice_marks_disabled_entries():
    from calango_cli import ui
    with patch("calango_cli.ui.questionary") as mock_q:
        mock_q.Choice.side_effect = lambda title, value, **kw: value
        mock_q.select.return_value.unsafe_ask.return_value = "postgres"
        ui.ask_choice(
            "Database",
            ["postgres", "mongo"],
            default="postgres",
            disabled={"mongo": "coming soon"},
        )
    calls = mock_q.Choice.call_args_list
    disabled_calls = [c for c in calls if c.kwargs.get("disabled")]
    assert len(disabled_calls) == 1
    assert "mongo" in str(disabled_calls[0])


def test_ask_confirm_delegates_to_questionary_confirm():
    from calango_cli import ui
    with patch("calango_cli.ui.questionary") as mock_q:
        mock_q.confirm.return_value.unsafe_ask.return_value = True
        result = ui.ask_confirm("Enable agents?", default=False)
    assert result is True
    mock_q.confirm.assert_called_once()
```

Note: the `patch("calango_cli.ui.questionary")` approach patches the entire questionary module as seen by `ui.py`. The `mock_q.Style` line keeps the real Style constructor so `_STYLE` (defined at module level) doesn't break — but since `_STYLE` is already evaluated at import time, this test approach patches after import, so it only affects the function calls inside `ask`, `ask_choice`, `ask_confirm`.

- [ ] **Step 2: Run the new tests**

```bash
uv run pytest packages/calango-cli/tests/test_ui.py -v 2>&1 | tail -20
```

Expected: all 14 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/calango-cli/tests/test_ui.py
git commit -m "test(cli/ui): questionary wrapper tests for ask, ask_choice, ask_confirm"
```

---

## Task 4: Update `main.py` — branded banner on no subcommand

**Files:**
- Modify: `packages/calango-cli/calango_cli/main.py`
- Modify: `packages/calango-cli/tests/test_new_command.py`

- [ ] **Step 1: Write failing test**

Append to `packages/calango-cli/tests/test_new_command.py`:

```python
def test_calango_no_args_shows_calango_brand():
    """calango with no args prints the calango. banner."""
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "calango" in result.output
```

- [ ] **Step 2: Run test — confirm it fails**

```bash
uv run pytest packages/calango-cli/tests/test_new_command.py::test_calango_no_args_shows_calango_brand -v
```

Expected: FAIL — the test either fails assertion or the banner isn't printed yet.

- [ ] **Step 3: Update `main.py`**

Replace the full content of `packages/calango-cli/calango_cli/main.py` with:

```python
import typer

from calango_cli.commands.generate import app as generate_app
from calango_cli.commands.new import new
from calango_cli.ui import print_banner

app = typer.Typer(name="calango", help="The fast, friendly Python web framework CLI.")
app.command("new")(new)
app.add_typer(generate_app, name="generate")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit."),
) -> None:
    """Calango CLI — The fast, friendly Python web framework."""
    if version:
        from calango import __version__

        typer.echo(f"calango {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        print_banner()
        typer.echo(ctx.get_help())
```

- [ ] **Step 4: Run all CLI tests — confirm no regressions**

```bash
uv run pytest packages/calango-cli/tests/ -v 2>&1 | tail -20
```

Expected: all tests pass, including the new banner test.

- [ ] **Step 5: Commit**

```bash
git add packages/calango-cli/calango_cli/main.py packages/calango-cli/tests/test_new_command.py
git commit -m "feat(cli): show branded banner when calango is invoked with no subcommand"
```

---

## Task 5: Update `commands/new.py` — Rich output + interactive wizard

**Files:**
- Modify: `packages/calango-cli/calango_cli/commands/new.py`
- Modify: `packages/calango-cli/tests/test_new_command.py`

- [ ] **Step 1: Write failing tests for the new behaviours**

Append to `packages/calango-cli/tests/test_new_command.py`:

```python
from unittest.mock import patch


def test_new_without_name_in_non_interactive_exits_1(tmp_path):
    """calango new with no name in a non-TTY environment exits 1."""
    result = runner.invoke(app, ["new", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_new_wizard_creates_project_directory(tmp_path):
    """calango new wizard scaffolds the project when run interactively."""
    with (
        patch("calango_cli.commands.new.is_interactive", return_value=True),
        patch("calango_cli.commands.new.print_banner"),
        patch("calango_cli.commands.new.ask", return_value="wizard-api"),
        patch("calango_cli.commands.new.ask_choice", side_effect=["postgres", "github"]),
        patch("calango_cli.commands.new.ask_confirm", return_value=False),
    ):
        result = runner.invoke(app, ["new", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "wizard-api").is_dir()


def test_new_wizard_project_contains_prompted_name(tmp_path):
    """Wizard-created project uses the name supplied by the prompt."""
    with (
        patch("calango_cli.commands.new.is_interactive", return_value=True),
        patch("calango_cli.commands.new.print_banner"),
        patch("calango_cli.commands.new.ask", return_value="wizard-api"),
        patch("calango_cli.commands.new.ask_choice", side_effect=["postgres", "github"]),
        patch("calango_cli.commands.new.ask_confirm", return_value=False),
    ):
        runner.invoke(app, ["new", "--path", str(tmp_path)])
    content = (tmp_path / "wizard-api" / "app" / "core" / "config.py").read_text()
    assert "wizard-api" in content
```

- [ ] **Step 2: Run the new tests — confirm they fail**

```bash
uv run pytest packages/calango-cli/tests/test_new_command.py::test_new_without_name_in_non_interactive_exits_1 packages/calango-cli/tests/test_new_command.py::test_new_wizard_creates_project_directory -v
```

Expected: both FAIL (Typer exits with code 2 for missing arg instead of 1, wizard test errors because no wizard exists).

- [ ] **Step 3: Rewrite `commands/new.py`**

Replace the full content of `packages/calango-cli/calango_cli/commands/new.py` with:

```python
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
        print_error(f"Directory '{project_dir}' already exists.")
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
```

- [ ] **Step 4: Run the full `test_new_command.py` suite**

```bash
uv run pytest packages/calango-cli/tests/test_new_command.py -v 2>&1 | tail -25
```

Expected: all tests pass (53 original + 3 new = 56 total).

- [ ] **Step 5: Commit**

```bash
git add packages/calango-cli/calango_cli/commands/new.py packages/calango-cli/tests/test_new_command.py
git commit -m "feat(cli/new): Rich output + interactive wizard with questionary"
```

---

## Task 6: Update `commands/generate.py` — Rich output + interactive wizard

**Files:**
- Modify: `packages/calango-cli/calango_cli/commands/generate.py`
- Modify: `packages/calango-cli/tests/test_generate_command.py`

- [ ] **Step 1: Write failing tests**

Append to `packages/calango-cli/tests/test_generate_command.py`:

```python
from unittest.mock import patch


def test_generate_resource_without_name_in_non_interactive_exits_1(tmp_path):
    """calango generate resource with no name in non-TTY exits 1."""
    _make_project(tmp_path)
    result = runner.invoke(app, ["generate", "resource", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_generate_resource_wizard_creates_all_files(tmp_path):
    """Interactive wizard creates all 8 resource files."""
    _make_project(tmp_path)
    with (
        patch("calango_cli.commands.generate.is_interactive", return_value=True),
        patch("calango_cli.commands.generate.ask", return_value="Order"),
    ):
        result = runner.invoke(app, ["generate", "resource", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "app" / "models" / "order.py").exists()


def test_generate_resource_wizard_validates_pascal_case(tmp_path):
    """Wizard rejects a resource name that does not start with uppercase."""
    _make_project(tmp_path)
    with (
        patch("calango_cli.commands.generate.is_interactive", return_value=True),
        patch("calango_cli.commands.generate.ask", return_value="order"),
    ):
        result = runner.invoke(app, ["generate", "resource", "--path", str(tmp_path)])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run the new tests — confirm they fail**

```bash
uv run pytest packages/calango-cli/tests/test_generate_command.py::test_generate_resource_without_name_in_non_interactive_exits_1 packages/calango-cli/tests/test_generate_command.py::test_generate_resource_wizard_creates_all_files -v
```

Expected: both FAIL.

- [ ] **Step 3: Rewrite `commands/generate.py`**

Replace the full content of `packages/calango-cli/calango_cli/commands/generate.py` with:

```python
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
```

- [ ] **Step 4: Run the full `test_generate_command.py` suite**

```bash
uv run pytest packages/calango-cli/tests/test_generate_command.py -v 2>&1 | tail -25
```

Expected: all tests pass (26 original + 3 new = 29 total).

- [ ] **Step 5: Run the complete test suite to check for any cross-package regressions**

```bash
uv run pytest packages/calango-cli/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass. Check exit code 0.

- [ ] **Step 6: Commit**

```bash
git add packages/calango-cli/calango_cli/commands/generate.py packages/calango-cli/tests/test_generate_command.py
git commit -m "feat(cli/generate): Rich output + interactive wizard for generate resource"
```

---

## Task 7: Documentation — CLI authoring guide

**Files:**
- Create: `packages/calango-cli/CLAUDE.md`
- Modify: `CLAUDE.md` (root)

- [ ] **Step 1: Create `packages/calango-cli/CLAUDE.md`**

Create `packages/calango-cli/CLAUDE.md` with this content:

```markdown
# calango-cli — CLI Authoring Guide

## Package overview

The CLI entry point is `calango_cli/main.py`. Commands live in `calango_cli/commands/`. All terminal output and interactive prompts go through `calango_cli/ui.py` — **never import `rich` or `questionary` directly in a command file**.

## Adding a new command

### 1. Create the command file

```python
# calango_cli/commands/my_cmd.py
from pathlib import Path
import typer
from calango_cli.ui import (
    ask, ask_choice, ask_confirm,
    is_interactive,
    print_banner, print_success, print_error, print_info, print_file_tree,
)

def my_cmd(
    name: str | None = typer.Argument(None, help="..."),
) -> None:
    """One-line description shown in calango --help."""
    if name is None:
        if not is_interactive():
            print_error("Missing argument 'NAME'.", hint="Run interactively: calango my-cmd")
            raise typer.Exit(1)
        name = ask("Name")

    # ... do work ...
    print_success(f"Done: {name}")
```

### 2. Register it in `main.py`

```python
from calango_cli.commands.my_cmd import my_cmd
app.command("my-cmd")(my_cmd)
```

### 3. Write tests first (TDD)

```python
# tests/test_my_cmd.py
from unittest.mock import patch
from typer.testing import CliRunner
from calango_cli.main import app

runner = CliRunner()

def test_my_cmd_exits_0(tmp_path):
    result = runner.invoke(app, ["my-cmd", "something"])
    assert result.exit_code == 0

def test_my_cmd_without_name_in_non_interactive_exits_1():
    result = runner.invoke(app, ["my-cmd"])
    assert result.exit_code == 1

def test_my_cmd_wizard_works():
    with (
        patch("calango_cli.commands.my_cmd.is_interactive", return_value=True),
        patch("calango_cli.commands.my_cmd.ask", return_value="test-name"),
    ):
        result = runner.invoke(app, ["my-cmd"])
    assert result.exit_code == 0
```

## `ui.py` API reference

| Function | When to use |
|---|---|
| `print_banner(subtitle="")` | Top of wizard flows and the main callback only — not on every command |
| `print_success(message, *, detail=None)` | After an operation completes successfully |
| `print_error(message, *, hint=None)` | On any failure; always include a `hint=` that guides the user |
| `print_info(label, fields: dict)` | Before starting an operation that takes more than a second |
| `print_file_tree(root, files)` | When a command creates multiple files |
| `ask(question, *, default="")` | Text prompt in a wizard; must be inside `if is_interactive()` |
| `ask_choice(question, choices, *, default, disabled=None)` | Select from a list; pass `disabled={"option": "reason"}` for coming-soon items |
| `ask_confirm(question, *, default=True)` | Yes/no prompt in a wizard |
| `is_interactive()` | Guard before any `ask*` call; returns False in CI, pipes, and tests |

## Color tokens

| Token | Hex | Meaning |
|---|---|---|
| `calango.primary` | `#2CBD6B` | Success, selected items, primary actions |
| `calango.primary.bright` | `#3FC878` | Hover, glow |
| `calango.accent` | `#E29A2E` | Amber accent, the dot in calango. |
| `calango.danger` | `#E5575C` | Errors |
| `calango.muted` | `#6A736E` | Secondary text, hints, dims |
| `calango.text` | `#A9B2AD` | Normal body text |

## Rules

1. **Never** call `rich.console.Console()` in a command file — use the singleton `console` from `ui.py` only if you need direct access, but prefer the helper functions.
2. **Never** call `questionary.*` in a command file — use `ask`, `ask_choice`, `ask_confirm`.
3. **Always** guard interactive prompts: `if not is_interactive(): print_error(...); raise typer.Exit(1)`.
4. **Always** provide `hint=` on every `print_error` call.
5. For `ask_choice`, use `disabled={"option": "reason"}` for unavailable options — never accept an option and then error after the fact.
6. `print_banner` appears only in wizard flows and the main callback — not as a header on every command execution.
```

- [ ] **Step 2: Add CLI conventions section to root `CLAUDE.md`**

In the root `CLAUDE.md`, find the `## Code conventions — follow strictly` section and add a new subsection after the existing naming and layered architecture subsections:

```markdown
### CLI conventions (`calango_cli/`)

All terminal output and interactive prompts are centralised in `calango_cli/ui.py`. Command files in `calango_cli/commands/` import only from `calango_cli.ui` — never from `rich` or `questionary` directly.

**Interactive pattern** — commands use `str | None` for required arguments and fall back to an interactive wizard when the arg is missing and `is_interactive()` is True:

```python
def my_cmd(name: str | None = typer.Argument(None, help="...")) -> None:
    if name is None:
        if not is_interactive():
            print_error("Missing argument 'NAME'.", hint="Run interactively: calango my-cmd")
            raise typer.Exit(1)
        name = ask("Name")
```

**CI safety** — flags always skip prompts. `is_interactive()` returns False when stdin or stdout is not a TTY, so scripts and CI pipelines never hang.

**Brand colors for the terminal** — use Rich style names from `ui._THEME`:
`calango.primary` (#2CBD6B), `calango.accent` (#E29A2E), `calango.danger` (#E5575C), `calango.muted` (#6A736E), `calango.text` (#A9B2AD).

See `packages/calango-cli/CLAUDE.md` for the full authoring guide.
```

- [ ] **Step 3: Run full test suite one final time**

```bash
uv run pytest packages/calango-cli/ -v --tb=short 2>&1 | tail -10
```

Expected: all tests pass, exit 0.

- [ ] **Step 4: Commit**

```bash
git add packages/calango-cli/CLAUDE.md CLAUDE.md
git commit -m "docs(cli): CLI authoring guide — ui.py API, color tokens, interactive pattern"
```

---

## Self-Review Checklist

- [x] `ui.py` public API matches every import used in `new.py`, `generate.py`, `main.py`
- [x] `ask_choice` `disabled` param defined in Task 2 and used in Task 5 with matching signature
- [x] `is_interactive()` guard present in both `new.py` and `generate.py` wizard paths
- [x] All 66 existing tests unaffected (they check file content / exit codes, not console strings)
- [x] `_render_resource_templates` no longer prints individual files (removed `console.print` line) — output now via `print_file_tree`
- [x] `_TEMPLATE_FILES` unchanged — scaffold output is identical
- [x] No `console = Console()` left in command files — removed from both `new.py` and `generate.py`
- [x] `pyproject.toml` update committed before `ui.py` creation (dependency available at test time)
- [x] `print_banner` called only in `main.py` callback and the `calango new` wizard — not on flag-driven `new` or `generate resource`
