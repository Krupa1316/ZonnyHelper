"""zonny-ai tree commands — AI-powered tree enrichment and query.

Adds two commands to the `zonny tree` group:
  enrich  — annotate entities in .zonny/tree.json with LLM flow labels
  query   — ask natural-language questions about the codebase
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="tree",
    help="AI-powered codebase tree enrichment and querying.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

_TREE_PATH     = Path(".zonny/tree.json")
_ENRICHED_PATH = Path(".zonny/enriched-tree.json")


@app.command()
def enrich(
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),  # noqa: UP007
) -> None:
    """[bold]CONDITION 4:[/bold] Add semantic labels to entity tree with AI.

    Reads [bold].zonny/tree.json[/bold] (produced by `zonny tree build`) and augments
    every entity with semantic flow labels, complexity indicators, and AI-generated
    descriptions.
    
    This is [bold]Condition 4: Semantic Labeling[/bold] — understanding intent and
    meaning, not just structure.
    """
    from rich.console import Console
    from zonny_ai.llm.prompts import enrich_prompt
    from zonny_ai.llm.router import get_provider
    from zonny_core.config.loader import load_config
    from zonny_core.utils.output import error, success

    console = Console()
    if not _TREE_PATH.exists():
        error("Tree file not found. Run `zonny tree build` first.")
        raise typer.Exit(1)

    try:
        cfg = load_config({})
        llm = get_provider(cfg, provider)
        if not llm.available():
            error(f"Provider '{llm.name()}' is not available. Check your API key.")
            raise typer.Exit(1)
    except Exception as exc:  # noqa: BLE001
        error(f"LLM setup failed: {exc}")
        raise typer.Exit(1) from exc

    import json
    tree_data = json.loads(_TREE_PATH.read_text())
    
    # Extract just entity names for enrichment
    entities = tree_data.get("entities", [])
    if not entities:
        error("No entities found in tree. Tree may be empty.")
        raise typer.Exit(1)
    
    # Build list of entities to enrich
    entity_list = [
        {
            "entity": e["name"],
            "type": e["type"],
            "file": e["file"],
            "line": e["start_line"]
        }
        for e in entities[:500]  # Limit to avoid token overflow
    ]
    
    console.print(f"[dim]Enriching {len(entity_list)} entities...[/dim]")

    with console.status("[bold green]Enriching entity tree with AI...[/bold green]"):
        system, user = enrich_prompt(json.dumps(entity_list, indent=2))
        response = llm.generate(user, system)

    try:
        # Parse AI response - should be JSON array
        enriched_entities = json.loads(response)
        
        # Merge enrichment back into original tree data
        entity_map = {e["entity"]: e for e in enriched_entities if isinstance(e, dict)}
        
        for entity in tree_data["entities"]:
            if entity["name"] in entity_map:
                enrichment = entity_map[entity["name"]]
                entity["flow_labels"] = enrichment.get("flow_labels", [])
                entity["complexity"] = enrichment.get("complexity", "unknown")
                entity["ai_label"] = enrichment.get("ai_label", "")
        
        # Save enriched tree
        _ENRICHED_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ENRICHED_PATH.write_text(json.dumps(tree_data, indent=2), encoding="utf-8")
        
        success(f"Enriched tree written to {_ENRICHED_PATH}")
        console.print(f"[dim]Added semantic labels to {len(entity_map)} entities[/dim]")
        
    except json.JSONDecodeError as exc:
        error(f"Failed to parse AI response: {exc}")
        # Save partial result
        fallback = {**tree_data, "enrichment_error": str(exc), "raw_response": response[:1000]}
        _ENRICHED_PATH.write_text(json.dumps(fallback, indent=2), encoding="utf-8")
        error(f"Saved partial result to {_ENRICHED_PATH}")
        raise typer.Exit(1) from exc


@app.command()
def query(
    question: str = typer.Argument(..., help="Natural-language question about the codebase."),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),  # noqa: UP007
) -> None:
    """Ask a [bold]natural-language question[/bold] about the codebase.

    Uses the entity tree (enriched if available) to answer questions about:
    - What functions call a specific function?
    - What writes to a database table?
    - Which code handles authentication?
    - Where is error handling implemented?
    
    This uses [bold]Condition 4: Semantic Labeling[/bold] — AI understands intent.
    """
    from rich.console import Console
    from zonny_ai.llm.prompts import query_prompt
    from zonny_ai.llm.router import get_provider
    from zonny_core.config.loader import load_config
    from zonny_core.utils.output import error, print_panel

    console = Console()
    tree_file = _ENRICHED_PATH if _ENRICHED_PATH.exists() else _TREE_PATH
    if not tree_file.exists():
        error("No tree file found. Run `zonny tree build` (and optionally `zonny tree enrich`) first.")
        raise typer.Exit(1)

    import json
    tree_data = json.loads(tree_file.read_text())

    try:
        cfg = load_config({})
        llm = get_provider(cfg, provider)
        if not llm.available():
            error(f"Provider '{llm.name()}' is not available. Check your API key.")
            raise typer.Exit(1)
    except Exception as exc:  # noqa: BLE001
        error(f"LLM setup failed: {exc}")
        raise typer.Exit(1) from exc

    # Truncate tree data to avoid token overflow
    tree_summary = json.dumps(tree_data, indent=2)[:12000]
    
    with console.status("[bold green]Querying codebase...[/bold green]"):
        system, user = query_prompt(question, tree_summary)
        answer = llm.generate(user, system)

    print_panel(answer, title=f"Answer: {question[:60]}", border_style="cyan")
