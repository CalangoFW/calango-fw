import typer

from calango_cli.commands.generate import app as generate_app
from calango_cli.commands.new import new

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
        typer.echo(ctx.get_help())
