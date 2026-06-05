# Calango CLI — Rich + questionary Redesign

**Date:** 2026-06-04  
**Status:** Approved  
**Scope:** `packages/calango-cli`

---

## Context

The Calango CLI currently uses Typer for command parsing and Rich for minimal colored output (`[green]✓[/green]`, `[red]Error:[/red]`). The UX is functional but bare — it lacks personality, branded identity, and interactive guidance for new users.

This redesign makes the CLI feel like a first-class citizen of the Calango brand: dark-first, technical, warm — born to live in the terminal. It introduces questionary for interactive wizards and a shared `ui.py` module that every future command can build on.

---

## Goals

1. **Friendly to newcomers** — `calango new` with no args launches a wizard instead of erroring.
2. **On-brand** — colors, prompt symbol (`›`), and banner match the Calango Brand Book.
3. **CI-safe** — flags always skip prompts; TTY auto-detection prevents hanging in scripts.
4. **Extensible** — all UI primitives live in `calango_cli/ui.py` so future commands (`db`, `plugin`, `test`, `context`) inherit the look without duplicating code.
5. **Documented** — `CLAUDE.md` gets a CLI authoring guide so any contributor (human or AI) knows how to add a new command correctly.

---

## Decisions

| Topic | Decision |
|---|---|
| Style | Branded + Interactive |
| Language | English (all user-facing text) |
| Interaction trigger | Auto-wizard when required arg is missing AND TTY is active |
| Flags | Always skip prompts — fully CI/pipe-safe |
| TTY detection | `sys.stdin.isatty() and sys.stdout.isatty()` |
| `calango new` wizard | Prompts: name → database → agents → CI provider |
| `calango generate resource` wizard | Prompts: resource name (PascalCase, with validation) |
| Banner placement | Only on `calango` with no subcommand (not on every command) |
| New dependency | `questionary >= 2.0` |

---

## Architecture

### New file: `calango_cli/ui.py`

The single source of truth for all terminal output and interactive prompts. Every command imports from here — no direct Rich or questionary calls in command files.

```python
# Public API surface
console: Console                         # Rich console, calango theme applied
theme: Theme                             # Rich Theme with brand tokens

def print_banner(subtitle: str = "") -> None: ...
def print_success(message: str, *, detail: str | None = None) -> None: ...
def print_error(message: str, *, hint: str | None = None) -> None: ...
def print_info(label: str, fields: dict[str, str]) -> None: ...
def print_file_tree(root: str, files: list[str]) -> None: ...

def ask(question: str, *, default: str = "") -> str: ...
def ask_choice(
    question: str,
    choices: list[str],
    *,
    default: str,
    disabled: dict[str, str] | None = None,  # {choice: reason}, e.g. {"mongo": "coming soon"}
) -> str: ...
def ask_confirm(question: str, *, default: bool = True) -> bool: ...

def is_interactive() -> bool: ...        # True only when stdin+stdout are TTY
```

**Color tokens** (from Calango Brand Book):

| Token | Hex | Rich style name |
|---|---|---|
| green-500 (primary) | `#2CBD6B` | `calango.primary` |
| green-400 (hover/glow) | `#3FC878` | `calango.primary.bright` |
| amber-500 (accent) | `#E29A2E` | `calango.accent` |
| danger | `#E5575C` | `calango.danger` |
| txt-2 (muted) | `#6A736E` | `calango.muted` |
| txt-1 (secondary) | `#A9B2AD` | `calango.text` |

Prompt symbol: `›` (matches brand book terminal aesthetic).

### Updated: `calango_cli/commands/new.py`

**Interactive path** (no `name` arg + `is_interactive()`):
1. `print_banner("new project")`
2. `ask("Project name")` → validates non-empty, no spaces
3. `ask_choice("Database", ["postgres", "mongo"], default="postgres", disabled={"mongo": "coming soon"})` — mongo is visible but greyed-out and cannot be selected
4. `ask_confirm("Enable agents plugin?", default=False)`
5. `ask_choice("CI provider", ["github", "gitlab"], default="github", disabled={"gitlab": "coming soon"})` — gitlab is visible but greyed-out
6. Run scaffold, then `print_file_tree` + next-step hint

**Non-interactive path** (name arg given OR no TTY):
- Same behavior as today but output replaced with `print_info` + `print_file_tree` + `print_success`

**Error path** (no arg, no TTY):
```
print_error("Missing argument 'NAME'.", hint="Run interactively: calango new")
```

### Updated: `calango_cli/commands/generate.py`

**Interactive path** (no `name` arg + `is_interactive()`):
1. `ask("Resource name (PascalCase, e.g. Order)")` → validates first char is uppercase
2. Run generation, then `print_file_tree` + `print_success`

**Non-interactive path** (name arg given OR no TTY):
- Same validation as today but output replaced with `print_file_tree` + `print_success`

### Updated: `calango_cli/main.py`

```python
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = ...) -> None:
    if version:
        ...
    if ctx.invoked_subcommand is None:
        print_banner()          # <-- new
        typer.echo(ctx.get_help())
```

### Updated: `packages/calango-cli/pyproject.toml`

```toml
dependencies = [
    "typer>=0.13",
    "jinja2>=3.1",
    "rich>=13",
    "questionary>=2.0",    # <-- new
    "calango-core",
]
```

### Documentation: `packages/calango-cli/CLAUDE.md`

New file (alongside the package) with the CLI authoring guide — see section below.

### Updated: root `CLAUDE.md`

Add a **CLI conventions** section under "Code conventions" documenting:
- Always import from `calango_cli.ui`, never from `rich` or `questionary` directly in command files
- Interactive pattern: check `is_interactive()` before calling `ask*` functions
- Color token reference table
- When to use each output function (`print_success` vs `print_info` vs `print_error`)

---

## CLI Authoring Guide (to be embedded in CLAUDE.md)

### Adding a new command

```python
# calango_cli/commands/my_cmd.py
import typer
from calango_cli.ui import (
    ask, ask_choice, ask_confirm,
    is_interactive, print_banner,
    print_success, print_error, print_info,
)

def my_cmd(
    name: str | None = typer.Argument(None, help="..."),
) -> None:
    """One-line description shown in --help."""
    if name is None:
        if not is_interactive():
            print_error("Missing argument 'NAME'.", hint="Run interactively: calango my-cmd")
            raise typer.Exit(1)
        name = ask("Name")

    # ... do work ...
    print_success(f"Done: {name}")
```

### Rules

1. **Never** import `rich` or `questionary` directly in command files — use `calango_cli.ui`.
2. **Always** guard interactive prompts with `is_interactive()` so CI never hangs.
3. **Always** provide a `hint=` on `print_error` calls that guide the user to the right command.
4. Use `print_banner(subtitle)` only at the top of wizard flows or the main callback — not on every command.
5. Use `print_file_tree(root, files)` whenever a command creates multiple files.
6. For `ask_choice`, pass unimplemented options via the `disabled=` dict — they appear greyed-out and cannot be selected. This is better than accepting them and erroring after the fact.

---

## Terminal UX Examples

### `calango` (no subcommand)
```
╭─ calango. ─────────────────────────────────────────────────╮
│  The fast, friendly Python web framework     v0.1.0-dev     │
╰────────────────────────────────────────────────────────────╯

Usage: calango [OPTIONS] COMMAND [ARGS]...
...
```

### `calango new` (wizard)
```
calango.  new project
────────────────────────────────
› Project name  › my-api
› Database      › ● postgres  ○ mongo
› Enable agents?› No
› CI provider   › ● github  ○ gitlab
────────────────────────────────
✓ Project created — my-api (21 files)
  ├─ app/
  ├─ .github/workflows/
  ├─ compose.yml
  └─ + 18 more files

Next: cd my-api && calango db migrate
```

### `calango new my-api --db=postgres` (flags, no prompts)
```
⬡ Creating project — my-api
  db      postgres
  ci      github
  agents  disabled

✓ Project created — my-api (21 files)
  ├─ app/  ...
```

### `calango generate resource` (interactive)
```
› Resource name (PascalCase) › Order

✓ Resource generated — Order (8 files)
  ├─ app/models/order.py
  ├─ app/schemas/order.py
  ├─ app/services/order.py
  └─ + 5 more files
```

---

## Testing Strategy

### Existing tests (must keep passing)
`CliRunner` from typer.testing does not attach a real TTY → `is_interactive()` returns `False` → no prompt code runs → all existing 66 tests pass unchanged.

### New tests to add

**`tests/test_ui.py`** — unit tests for every function in `ui.py`:
- `is_interactive()` returns False when stdin is not a TTY (always in test env)
- `print_success`, `print_error`, `print_info` render without exceptions
- `print_file_tree` renders correct tree structure

**`tests/test_new_command.py`** — add interactive wizard path:
- Use `CliRunner(mix_stderr=False)` + `input=` to simulate questionary answers
- Assert correct project is scaffolded when wizard completes
- Assert `print_error` output when no arg and not interactive

**`tests/test_generate_command.py`** — add interactive path:
- Simulate resource name via `input=`
- Assert 8 files generated correctly
- Assert PascalCase validation error shown for invalid names

---

## Files Changed

| File | Change |
|---|---|
| `packages/calango-cli/calango_cli/ui.py` | **New** — shared UI module |
| `packages/calango-cli/calango_cli/commands/new.py` | Updated — wizard + Rich output |
| `packages/calango-cli/calango_cli/commands/generate.py` | Updated — wizard + Rich output |
| `packages/calango-cli/calango_cli/main.py` | Updated — banner on no-subcommand |
| `packages/calango-cli/pyproject.toml` | Updated — add `questionary>=2.0` |
| `packages/calango-cli/CLAUDE.md` | **New** — CLI authoring guide |
| `CLAUDE.md` (root) | Updated — CLI conventions section |
| `packages/calango-cli/tests/test_ui.py` | **New** — ui.py unit tests |
| `packages/calango-cli/tests/test_new_command.py` | Updated — wizard test cases |
| `packages/calango-cli/tests/test_generate_command.py` | Updated — wizard test cases |

---

## Out of Scope

- Commands not yet implemented (`db`, `plugin`, `test`, `context`) — `ui.py` is the foundation they'll build on, but they are not implemented here.
- `calango generate model`, `generate service`, etc. — not yet implemented.
- Changing the Typer framework itself — Typer stays.
- Changing template rendering logic — Jinja2 templates unchanged.
