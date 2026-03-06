"""Configuration loader for zonny-helper.

Merges configuration from four sources (lowest to highest priority):
  1. Built-in defaults
  2. Global config:  ~/.config/zonny/config.toml
  3. Project config: .zonny.toml  (found by walking up from CWD)
  4. Environment variables  (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
  5. CLI overrides  (passed as dict from command callbacks)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from zonny_helper.config.defaults import DEFAULTS
from zonny_helper.config.schema import ZonnyConfig

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into `base`, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_toml(path: Path) -> dict:
    """Load a TOML file; return empty dict if not found or malformed."""
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _global_config_path() -> Path:
    """Return the platform-appropriate global config file path."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "zonny" / "config.toml"


def _find_project_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` to find the nearest .zonny.toml file."""
    current = (start or Path.cwd()).resolve()
    for parent in [current] + list(current.parents):
        candidate = parent / ".zonny.toml"
        if candidate.exists():
            return candidate
        # Stop at filesystem root
        if parent == parent.parent:
            break
    return None


def _env_overrides() -> dict:
    """Build an override dict from well-known environment variables."""
    overrides: dict[str, Any] = {}

    env_map = {
        "ANTHROPIC_API_KEY": ["llm", "anthropic", "api_key"],
        "OPENAI_API_KEY":    ["llm", "openai",    "api_key"],
        "GOOGLE_API_KEY":    ["llm", "gemini",    "api_key"],
        "ZONNY_PROVIDER":    ["llm", "provider"],
        "ZONNY_OUTPUT":      ["general", "output_format"],
    }

    for env_var, key_path in env_map.items():
        value = os.environ.get(env_var)
        if value:
            target: dict = overrides
            for part in key_path[:-1]:
                target = target.setdefault(part, {})
            target[key_path[-1]] = value

    return overrides


def load_config(cli_overrides: dict | None = None) -> ZonnyConfig:
    """Load and merge configuration from all sources, return a validated ZonnyConfig."""
    merged: dict = dict(DEFAULTS)

    # 1. Global config
    merged = _deep_merge(merged, _load_toml(_global_config_path()))

    # 2. Project config (nearest .zonny.toml walking up from CWD)
    project_cfg = _find_project_config()
    if project_cfg:
        merged = _deep_merge(merged, _load_toml(project_cfg))

    # 3. Environment variables
    merged = _deep_merge(merged, _env_overrides())

    # 4. CLI overrides
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    return ZonnyConfig.model_validate(merged)
