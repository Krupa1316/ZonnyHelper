"""Core git commands for zonny-core (no LLM required).

These commands perform raw git operations that produce deterministic output.
LLM-powered commands (commit, pr, whybroke) are provided by zonny-ai.
"""
from __future__ import annotations

import sys

import typer
from rich.console import Console

from zonny_core.utils.git_utils import (
    get_branch_diff,
    get_log,
    get_staged_diff,
    is_git_repo,
)
from zonny_core.utils.output import error, print_panel, warn

app = typer.Typer(
    name="git",
    help="Git utilities and AI-powered workflow automation.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()


@app.command()
def diff(
    cached: bool = typer.Option(True, "--cached/--working", help="Show staged (--cached) or working diff."),
    base: str = typer.Option("", "--base", "-b", help="Compare against this branch instead of staged diff."),
    stat: bool = typer.Option(False, "--stat", help="Show diffstat summary instead of full diff."),
) -> None:
    """Show the current git diff (staged or branch diff).

    Use [bold]--base <branch>[/bold] to compare current branch against another branch.
    """
    if not is_git_repo():
        error("Not a git repository.")
        raise typer.Exit(1)

    try:
        raw = get_branch_diff(base) if base else get_staged_diff()
    except Exception as exc:  # noqa: BLE001
        error(f"Git error: {exc}")
        raise typer.Exit(1) from exc

    if not raw.strip():
        warn("No diff found.")
        raise typer.Exit(0)

    if stat:
        # Print a quick stat summary from parsed diff
        from zonny_core.git.diff_parser import diff_stats, parse_diff
        files = parse_diff(raw)
        stats = diff_stats(files)
        console.print(
            f"[bold]{stats['files_changed']}[/bold] file(s) changed, "
            f"[green]+{stats['additions']}[/green] insertions, "
            f"[red]-{stats['deletions']}[/red] deletions"
        )
    else:
        console.print(raw)


@app.command()
def log(
    from_ref: str = typer.Option("", "--from", help="Start ref (tag or SHA)."),
    to_ref: str = typer.Option("HEAD", "--to", help="End ref (default: HEAD)."),
    n: int = typer.Option(20, "--num", "-n", help="Max commits to show."),
) -> None:
    """Show git commit log for a ref range."""
    if not is_git_repo():
        error("Not a git repository.")
        raise typer.Exit(1)

    try:
        log_text = get_log(from_ref, to_ref)
    except Exception as exc:  # noqa: BLE001
        error(f"Git error: {exc}")
        raise typer.Exit(1) from exc

    if not log_text.strip():
        warn("No commits found in the specified range.")
        raise typer.Exit(0)

    lines = log_text.splitlines()[:n]
    print_panel("\n".join(lines), title=f"Git Log ({from_ref or 'beginning'} → {to_ref})", border_style="cyan")
