"""Codebase Tree commands — Typer sub-application.

Provides deterministic tree building using tree-sitter for structural parsing.
AI-powered semantic enrichment is in zonny-ai (Condition 4).
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="tree",
    help="Codebase entity tree intelligence.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()


@app.command()
def build(
    root: Path = typer.Argument(Path("."), help="Repository root directory."),
    output: Path = typer.Option(Path(".zonny/tree.json"), "--output", "-o", help="Output path for the tree JSON."),
    languages: str = typer.Option("", "--languages", help="Comma-separated language list (e.g., 'python,javascript'). Leave empty to parse ALL languages."),
    max_depth: int = typer.Option(None, "--max-depth", help="Max directory depth."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Build a complete entity tree for the repository.
    
    Supports 20+ languages with tree-sitter + regex fallback.
    Automatically detects: Python, JavaScript, TypeScript, Java, C, C++, Go,
    Rust, Ruby, PHP, C#, Kotlin, Swift, and many more.
    
    Uses universal patterns for unknown languages, so it works with ANY
    programming language!
    
    For semantic enrichment (Condition 4), run `zonny tree enrich` afterwards.
    """
    from zonny_core.tree.builder import build_tree
    from zonny_core.utils.output import error, info, success
    
    # Validate root
    if not root.exists():
        error(f"Repository root not found: {root}")
        raise typer.Exit(1)
    
    # Parse languages list
    lang_list = None
    if languages:
        lang_list = [l.strip() for l in languages.split(",")]
    
    # Build tree
    with console.status("[bold green]Building entity tree...[/bold green]"):
        try:
            tree = build_tree(root, languages=lang_list, max_depth=max_depth)
        except Exception as exc:
            error(f"Failed to build tree: {exc}")
            raise typer.Exit(1) from exc
    
    # Write output
    try:
        tree.write(output)
    except Exception as exc:
        error(f"Failed to write tree: {exc}")
        raise typer.Exit(1) from exc
    
    # Display summary
    if json_output:
        import json
        print(json.dumps(tree.to_dict()))
    else:
        success(f"Tree built: {len(tree.entities)} entities from {len(tree.files)} files")
        console.print(f"\n[bold]Languages:[/bold]")
        for lang, count in tree.languages.items():
            console.print(f"  • {lang}: {count} files")
        console.print(f"\n[bold]Output:[/bold] {output}")
        info("Run [bold]zonny tree enrich[/bold] to add semantic labels (Condition 4)")


@app.command()
def query(
    question: str = typer.Argument(..., help="Natural language question about the codebase."),
) -> None:
    """Ask a natural language question about the codebase.
    
    This command requires zonny-ai. Use `zonny tree enrich` then `zonny tree query`.
    """
    from zonny_core.utils.output import error
    
    error("This command requires zonny-ai package")
    raise typer.Exit(1)


@app.command()
def diff(
    ref1: str = typer.Argument(..., help="First branch or commit ref."),
    ref2: str = typer.Argument(..., help="Second branch or commit ref."),
    output: Path = typer.Option(None, "--output", "-o", help="Write diff JSON to file."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show structural entity differences between two git refs.
    
    Compares entity trees between two git refs and shows added/removed/modified entities.
    """
    from zonny_core.tree.builder import Tree, build_tree
    from zonny_core.utils.output import error, success
    import subprocess
    import tempfile
    
    # Check we're in a git repo
    try:
        subprocess.run(["git", "rev-parse", "--git-dir"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        error("Not a git repository")
        raise typer.Exit(1)
    
    with console.status(f"[bold green]Comparing {ref1} vs {ref2}...[/bold green]"):
        # Get current branch to restore later
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        
        try:
            # Build tree for ref1
            subprocess.run(["git", "checkout", ref1], check=True, capture_output=True)
            tree1 = build_tree(Path("."))
            
            # Build tree for ref2
            subprocess.run(["git", "checkout", ref2], check=True, capture_output=True)
            tree2 = build_tree(Path("."))
            
        finally:
            # Restore original branch
            subprocess.run(["git", "checkout", current], check=True, capture_output=True)
    
    # Compare entities
    entities1 = {e.name: e for e in tree1.entities}
    entities2 = {e.name: e for e in tree2.entities}
    
    added = [e for name, e in entities2.items() if name not in entities1]
    removed = [e for name, e in entities1.items() if name not in entities2]
    common = [name for name in entities1 if name in entities2]
    
    diff_data = {
        "ref1": ref1,
        "ref2": ref2,
        "added": [e.to_dict() for e in added],
        "removed": [e.to_dict() for e in removed],
        "common": len(common),
    }
    
    if json_output:
        import json
        if output:
            output.write_text(json.dumps(diff_data, indent=2))
            success(f"Diff written to {output}")
        else:
            print(json.dumps(diff_data, indent=2))
    else:
        console.print(f"\n[bold]Diff {ref1} → {ref2}:[/bold]")
        console.print(f"  [green]+ Added:[/green] {len(added)} entities")
        for e in added[:10]:
            console.print(f"    + {e.type} {e.name} in {e.file}:{e.start_line}")
        if len(added) > 10:
            console.print(f"    ... and {len(added) - 10} more")
        
        console.print(f"  [red]- Removed:[/red] {len(removed)} entities")
        for e in removed[:10]:
            console.print(f"    - {e.type} {e.name} in {e.file}:{e.start_line}")
        if len(removed) > 10:
            console.print(f"    ... and {len(removed) - 10} more")
        
        console.print(f"  [dim]= Unchanged:[/dim] {len(common)} entities")
        
        if output:
            import json
            output.write_text(json.dumps(diff_data, indent=2))
            success(f"\nFull diff written to {output}")


@app.command()
def export(
    tree_path: Path = typer.Argument(Path(".zonny/tree.json"), help="Path to tree JSON."),
    format_: str = typer.Option("md", "--format", "-f", help="Output format: md | mermaid."),
    output: Path = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    """Export the entity tree to Markdown or Mermaid diagram."""
    from zonny_core.tree.builder import Tree
    from zonny_core.utils.output import error, success
    
    if not tree_path.exists():
        error(f"Tree file not found: {tree_path}")
        error("Run [bold]zonny tree build[/bold] first")
        raise typer.Exit(1)
    
    tree = Tree.load(tree_path)
    
    if format_ == "md":
        content = _export_markdown(tree)
    elif format_ == "mermaid":
        content = _export_mermaid(tree)
    else:
        error(f"Unknown format: {format_}. Use 'md' or 'mermaid'")
        raise typer.Exit(1)
    
    if output:
        output.write_text(content, encoding="utf-8")
        success(f"Exported to {output}")
    else:
        print(content)


def _export_markdown(tree: Tree) -> str:
    """Export tree as Markdown."""
    from zonny_core.tree.builder import Tree
    
    lines = ["# Codebase Entity Tree\n"]
    lines.append(f"**Total Entities:** {len(tree.entities)}\n")
    lines.append(f"**Total Files:** {len(tree.files)}\n")
    
    lines.append("\n## Languages\n")
    for lang, count in tree.languages.items():
        lines.append(f"- **{lang}:** {count} files\n")
    
    lines.append("\n## Entities\n")
    
    # Group by file
    by_file: dict[str, list] = {}
    for e in tree.entities:
        by_file.setdefault(e.file, []).append(e)
    
    for file in sorted(by_file.keys()):
        lines.append(f"\n### {file}\n")
        for e in sorted(by_file[file], key=lambda x: x.start_line):
            parent_info = f" (in {e.parent})" if e.parent else ""
            lines.append(f"- **{e.type}** `{e.name}`{parent_info} — Line {e.start_line}\n")
    
    return "".join(lines)


def _export_mermaid(tree: Tree) -> str:
    """Export tree as Mermaid diagram."""
    from zonny_core.tree.builder import Tree
    
    lines = ["```mermaid\n", "graph TD\n"]
    
    # Create nodes for classes
    classes = [e for e in tree.entities if e.type == "class"]
    for cls in classes:
        lines.append(f"    {cls.name}[{cls.name}]\n")
    
    # Add methods to classes
    for method in [e for e in tree.entities if e.parent]:
        lines.append(f"    {method.parent} --> {method.name}{{'{method.name}()'}}\n")
    
    lines.append("```\n")
    return "".join(lines)
