"""zonny config — API key & project configuration management.

All keys are stored in ~/.zonny/config.toml with file permissions 600
(owner read/write only) — they never touch the project directory.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import typer

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w
from rich.console import Console
from rich.table import Table

from zonny_core.utils.output import error, success, warn

app = typer.Typer(
    name="config",
    help="Manage API keys, defaults, and project configuration.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()

# ── Config file location ──────────────────────────────────────────────────────

_GLOBAL_CONFIG_DIR  = Path.home() / ".zonny"
_GLOBAL_CONFIG_FILE = _GLOBAL_CONFIG_DIR / "config.toml"

_SUPPORTED_PROVIDERS = ("anthropic", "openai", "gemini", "ollama")

_DEFAULT_CONFIG: dict[str, Any] = {
    "keys": {
        "anthropic": "",
        "openai": "",
        "gemini": "",
        "ollama": "",
    },
    "defaults": {
        "ai_provider": "anthropic",
        "deploy_target": "docker-compose",
        "tree_output": ".zonny/tree.json",
    },
    "ignore": {
        "patterns": ["node_modules/", ".git/", "dist/", "__pycache__/"],
    },
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_config() -> dict[str, Any]:
    """Load global config file, returning defaults if file doesn't exist."""
    if not _GLOBAL_CONFIG_FILE.exists():
        return {k: dict(v) for k, v in _DEFAULT_CONFIG.items()}
    with open(_GLOBAL_CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def _save_config(cfg: dict[str, Any]) -> None:
    """Write config to ~/.zonny/config.toml with 600 permissions."""
    _GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_GLOBAL_CONFIG_FILE, "wb") as f:
        tomli_w.dump(cfg, f)
    # Set permissions to 600 (owner read/write only) — no-op on Windows but safe
    try:
        os.chmod(_GLOBAL_CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except (AttributeError, NotImplementedError):
        pass  # Windows does not support Unix-style chmod


def _mask_key(key: str) -> str:
    """Mask an API key for safe display."""
    if not key or len(key) < 8:
        return "[dim](not set)[/dim]"
    return key[:7] + "***" + key[-3:]


def _deep_set(cfg: dict, section: str, key: str, value: Any) -> None:
    """Set cfg[section][key] = value, creating section if needed."""
    if section not in cfg:
        cfg[section] = {}
    cfg[section][key] = value


# ── Commands ──────────────────────────────────────────────────────────────────

@app.command("set-key")
def set_key(
    provider: str = typer.Argument(..., help=f"Provider name: {', '.join(_SUPPORTED_PROVIDERS)}"),
    key: str = typer.Argument(..., help="API key value."),
) -> None:
    """Store an API key securely in [bold]~/.zonny/config.toml[/bold].

    Keys are masked in `zonny config list` output and never stored in
    the project directory — safe from accidental git commits.

    Examples:
      zonny config set-key anthropic sk-ant-api03-...
      zonny config set-key openai sk-proj-...
    """
    provider = provider.lower()
    if provider not in _SUPPORTED_PROVIDERS:
        error(f"Unknown provider '{provider}'. Supported: {', '.join(_SUPPORTED_PROVIDERS)}")
        raise typer.Exit(1)

    cfg = _load_config()
    if "keys" not in cfg:
        cfg["keys"] = {}
    cfg["keys"][provider] = key
    _save_config(cfg)
    success(f"Key saved to {_GLOBAL_CONFIG_FILE}  [dim](permissions: 600)[/dim]")


@app.command("unset-key")
def unset_key(
    provider: str = typer.Argument(..., help="Provider whose key to remove."),
) -> None:
    """Remove a stored API key for the given provider."""
    provider = provider.lower()
    cfg = _load_config()
    if cfg.get("keys", {}).get(provider):
        cfg["keys"][provider] = ""
        _save_config(cfg)
        success(f"Key for '{provider}' removed.")
    else:
        warn(f"No key found for '{provider}'.")


@app.command("list")
def list_config() -> None:
    """Show current configuration. API keys are masked for safety."""
    cfg = _load_config()

    # ── Keys table ────────────────────────────────────────────────────────────
    key_table = Table(title="API Keys", show_header=True, header_style="bold cyan")
    key_table.add_column("Provider", style="bold")
    key_table.add_column("Status")
    key_table.add_column("Masked Value")

    keys = cfg.get("keys", {})
    for p in _SUPPORTED_PROVIDERS:
        val = keys.get(p, "")
        status = "[green]configured[/green]" if val else "[red]not set[/red]"
        key_table.add_row(p, status, _mask_key(val))

    console.print(key_table)

    # ── Defaults table ────────────────────────────────────────────────────────
    defaults = cfg.get("defaults", {})
    if defaults:
        console.print()
        def_table = Table(title="Defaults", show_header=True, header_style="bold yellow")
        def_table.add_column("Key", style="bold")
        def_table.add_column("Value")
        for k, v in defaults.items():
            def_table.add_row(k, str(v))
        console.print(def_table)

    # ── Ignore patterns ───────────────────────────────────────────────────────
    patterns = cfg.get("ignore", {}).get("patterns", [])
    if patterns:
        console.print(f"\n[bold]Ignore patterns:[/bold] {', '.join(patterns)}")

    console.print(f"\n[dim]Config file: {_GLOBAL_CONFIG_FILE}[/dim]")


@app.command("set")
def set_value(
    key: str = typer.Argument(..., help="Config key in dot notation, e.g. defaults.deploy_target"),
    value: str = typer.Argument(..., help="Value to set."),
) -> None:
    """Set a configuration value.

    Use dot notation for nested keys:
      zonny config set defaults.deploy_target kubernetes
      zonny config set defaults.ai_provider gemini
    """
    cfg = _load_config()
    parts = key.split(".", 1)
    if len(parts) == 2:
        section, subkey = parts
    else:
        error("Key must use dot notation: <section>.<key>  e.g. defaults.deploy_target")
        raise typer.Exit(1)

    _deep_set(cfg, section, subkey, value)
    _save_config(cfg)
    success(f"Set [bold]{key}[/bold] = {value}")


@app.command("get")
def get_value(
    key: str = typer.Argument(..., help="Config key in dot notation, e.g. defaults.deploy_target"),
) -> None:
    """Read a single configuration value."""
    cfg = _load_config()
    parts = key.split(".", 1)
    if len(parts) == 2:
        section, subkey = parts
        val = cfg.get(section, {}).get(subkey)
    else:
        val = cfg.get(key)

    if val is None:
        warn(f"Key '{key}' not found in config.")
        raise typer.Exit(1)

    # Never print API keys raw — always mask them
    if parts[0] == "keys":
        console.print(_mask_key(str(val)))
    else:
        console.print(str(val))
