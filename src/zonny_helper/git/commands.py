"""Git workflow commands — Typer sub-application.

Phase 2 placeholder: commands are stubbed out so the CLI loads cleanly.
Full implementations are added in Phase 2 of the development plan.
"""
from __future__ import annotations

import typer

app = typer.Typer(
    name="git",
    help="AI-powered git workflow automation.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command()
def commit(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show generated message without committing."),
    execute: bool = typer.Option(False, "--execute", help="Auto-run `git commit` after generating."),
    type_: str = typer.Option("", "--type", "-t", help="Commit type hint (feat, fix, chore, ...)."),
    scope: str = typer.Option("", "--scope", "-s", help="Commit scope hint."),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM provider override."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Generate a conventional commit message from staged changes."""
    typer.echo("[Phase 2] zonny git commit — coming soon!")


@app.command()
def pr(
    base: str = typer.Option("main", "--base", "-b", help="Base branch to diff against."),
    template: str = typer.Option(None, "--template", help="Path to a PR template file."),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM provider override."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Generate a PR title and description from branch diff."""
    typer.echo("[Phase 2] zonny git pr — coming soon!")


@app.command()
def changelog(
    from_ref: str = typer.Option("", "--from", help="Start ref (tag or commit)."),
    to_ref: str = typer.Option("HEAD", "--to", help="End ref."),
    format_: str = typer.Option("md", "--format", help="Output format: md | json."),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM provider override."),
) -> None:
    """Generate a CHANGELOG from git log entries."""
    typer.echo("[Phase 2] zonny git changelog — coming soon!")


@app.command()
def whybroke(
    log: str = typer.Option(None, "--log", "-l", help="Path to CI log file."),
    ci: str = typer.Option("github-actions", "--ci", help="CI system type."),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM provider override."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Diagnose a CI failure from logs and recent diff."""
    typer.echo("[Phase 2] zonny git whybroke — coming soon!")
