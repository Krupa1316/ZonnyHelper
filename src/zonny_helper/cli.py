"""Zonny Helper CLI root application.

Registers the `git` and `tree` sub-command groups under the `zonny` entry-point
and handles top-level flags (--version, --provider).
"""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from zonny_helper import __version__

console = Console()

app = typer.Typer(
    name="zonny",
    help=(
        "[bold green]Zonny Helper[/bold green] — AI-powered developer intelligence CLI.\n\n"
        "  [dim]git automation  ·  codebase intelligence  ·  agent-ready output[/dim]"
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=True,
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]zonny-helper[/bold] v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(  # noqa: UP007
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Zonny Helper — Your codebase, finally understood."""


# ── Register sub-applications ─────────────────────────────────────────────────
# Import is deferred here so that missing optional deps only fail when the
# specific sub-command is invoked, not at CLI startup.

def _load_git_app() -> None:
    from zonny_helper.git.commands import app as git_app  # noqa: PLC0415
    app.add_typer(git_app, name="git", help="AI git workflow automation.")


def _load_tree_app() -> None:
    from zonny_helper.tree.commands import app as tree_app  # noqa: PLC0415
    app.add_typer(tree_app, name="tree", help="Codebase entity tree intelligence.")


_load_git_app()
_load_tree_app()
