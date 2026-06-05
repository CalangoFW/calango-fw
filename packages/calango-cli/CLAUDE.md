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
