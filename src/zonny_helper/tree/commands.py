"""Codebase Tree commands — Typer sub-application.

Phase 3/4 placeholder: commands are stubbed out so the CLI loads cleanly.
Full implementations are added in Phases 3 and 4 of the development plan.
"""
from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    name="tree",
    help="Codebase entity tree intelligence.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command()
def build(
    root: Path = typer.Argument(Path("."), help="Repository root directory."),
    output: Path = typer.Option(Path("tree.json"), "--output", "-o", help="Output path for the tree JSON."),
    no_enrich: bool = typer.Option(False, "--no-enrich", help="Skip LLM enrichment."),
    languages: str = typer.Option("", "--languages", help="Comma-separated language list."),
    max_depth: int = typer.Option(None, "--max-depth", help="Max directory depth."),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM provider override."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Build a complete entity tree for the repository."""
    typer.echo("[Phase 3] zonny tree build — coming soon!")


@app.command()
def query(
    question: str = typer.Argument(..., help="Natural language question about the codebase."),
    tree_path: Path = typer.Option(Path("tree.json"), "--tree", "-t", help="Path to pre-built tree JSON."),
    provider: str = typer.Option(None, "--provider", "-p", help="LLM provider override."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Ask a natural language question about the codebase."""
    typer.echo("[Phase 4] zonny tree query — coming soon!")


@app.command()
def diff(
    ref1: str = typer.Argument(..., help="First branch or commit ref."),
    ref2: str = typer.Argument(..., help="Second branch or commit ref."),
    output: Path = typer.Option(None, "--output", "-o", help="Write diff JSON to file."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show structural entity differences between two git refs."""
    typer.echo("[Phase 4] zonny tree diff — coming soon!")


@app.command()
def export(
    tree_path: Path = typer.Argument(Path("tree.json"), help="Path to tree JSON."),
    format_: str = typer.Option("md", "--format", "-f", help="Output format: md | mermaid."),
    output: Path = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    """Export the entity tree to Markdown or Mermaid diagram."""
    typer.echo("[Phase 4] zonny tree export — coming soon!")
