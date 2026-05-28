from pathlib import Path

import typer
from rich.console import Console

console = Console()


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
    console.print(f"[green]✓[/green]  Created project: {name}")
    # Templates will be generated here in subsequent tasks
