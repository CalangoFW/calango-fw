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
        f"› {question}",  # noqa: RUF001
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
        f"› {question}",  # noqa: RUF001
        choices=qchoices,
        default=default,
        style=_STYLE,
    ).unsafe_ask()


def ask_confirm(question: str, *, default: bool = True) -> bool:
    """Prompt for a yes/no confirmation."""
    return questionary.confirm(
        f"› {question}",  # noqa: RUF001
        default=default,
        style=_STYLE,
    ).unsafe_ask()
