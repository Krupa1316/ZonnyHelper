"""zonny-core root CLI entry point.

Registers sub-command groups owned by zonny-core (deploy, git-diff, tree, config).
When zonny-ai is also installed, it extends this app at import time via its
entry-point hook, adding AI-powered commands to each group.
"""
from __future__ import annotations

import importlib
import importlib.metadata
from typing import Optional

import typer
from rich.console import Console

from zonny_core import __version__

app = typer.Typer(
    name="zonny",
    help="[bold green]Zonny[/bold green] â€” commit smarter, understand everything, deploy anything.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


# â”€â”€ Sub-app registration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _register_core_commands() -> None:
    from zonny_core.deploy.commands import app as deploy_app
    from zonny_core.config.commands import app as config_app
    from zonny_core.tree.commands import app as tree_app
    from zonny_core.git.commands import app as git_app

    app.add_typer(deploy_app, name="deploy")
    app.add_typer(config_app, name="config")
    app.add_typer(tree_app,   name="tree")
    app.add_typer(git_app,    name="git")


def _load_ai_extensions() -> None:
    """If zonny-ai is installed, let it attach AI commands to our app."""
    try:
        eps = importlib.metadata.entry_points(group="zonny_core.extensions")
        for ep in eps:
            attach_fn = ep.load()
            attach_fn(app)
    except Exception:  # noqa: BLE001
        pass  # zonny-ai not installed â€” silently skip


_register_core_commands()
_load_ai_extensions()


# â”€â”€ Root callbacks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.callback()
def main(
    version: Optional[bool] = typer.Option(  # noqa: UP007
        None,
        "--version",
        "-V",
        help="Show version and exit.",
        is_eager=True,
    ),
) -> None:
    """[bold green]Zonny[/bold green] developer platform."""
    if version:
        pkgs = []
        for name in ("zonny-core", "zonny-ai"):
            try:
                pkgs.append(f"{name}=={importlib.metadata.version(name)}")
            except importlib.metadata.PackageNotFoundError:
                pass
        console.print("  ".join(pkgs) or f"zonny-core=={__version__}")
        raise typer.Exit()
