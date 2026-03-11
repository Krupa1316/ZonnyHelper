"""Rich console output helpers for zonny-helper CLI."""
from __future__ import annotations

import json

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def error(message: str) -> None:
    """Print a formatted error message to stderr."""
    err_console.print(f"[bold red]âœ—[/bold red] {message}")


def warn(message: str) -> None:
    """Print a formatted warning message."""
    console.print(f"[bold yellow]âš [/bold yellow]  {message}")


def success(message: str) -> None:
    """Print a formatted success message."""
    console.print(f"[bold green]âœ“[/bold green] {message}")


def info(message: str) -> None:
    """Print a formatted info message."""
    console.print(f"[dim]â†’[/dim] {message}")


def print_panel(content: str, title: str = "", border_style: str = "green") -> None:
    """Print content inside a Rich panel."""
    console.print(Panel(content, title=f"[bold]{title}[/bold]" if title else "", border_style=border_style))


def print_json(data: dict | list) -> None:
    """Print data as pretty-printed, syntax-highlighted JSON."""
    raw = json.dumps(data, indent=2, default=str)
    syntax = Syntax(raw, "json", theme="monokai", line_numbers=False)
    console.print(syntax)


def print_table(headers: list[str], rows: list[list[str]], title: str = "") -> None:
    """Print a Rich table with the given headers and rows."""
    table = Table(title=title, show_header=True, header_style="bold magenta")
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*row)
    console.print(table)


def banner() -> None:
    """Print the Zonny Helper ASCII banner."""
    console.print(
        "\n[bold green]  â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—[/bold green]"
        "\n[bold green]  â•‘     Zonny Helper  v[/bold green][cyan]0.1.0[/cyan][bold green]         â•‘[/bold green]"
        "\n[bold green]  â•‘  Developer Intelligence CLI       â•‘[/bold green]"
        "\n[bold green]  â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•[/bold green]\n"
    )
