r"""Simple file-based LLM response cache for zonny-helper.

Caches responses by a hash of (provider, model, prompt, system) so that
identical requests don't make redundant API calls during development.

Cache is stored at:  ~/.cache/zonny/llm_cache/  (or %LOCALAPPDATA%\zonny\llm_cache\ on Windows)
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def _cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "zonny" / "llm_cache"


def _cache_key(provider: str, model: str, prompt: str, system: str) -> str:
    raw = f"{provider}::{model}::{system}::{prompt}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached(provider: str, model: str, prompt: str, system: str) -> str | None:
    """Return cached response text if available, else None."""
    key = _cache_key(provider, model, prompt, system)
    path = _cache_dir() / f"{key}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("response")
        except Exception:
            return None
    return None


def set_cached(provider: str, model: str, prompt: str, system: str, response: str) -> None:
    """Store a response in the cache."""
    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(provider, model, prompt, system)
    path = cache_dir / f"{key}.json"
    path.write_text(
        json.dumps({"provider": provider, "model": model, "response": response}, indent=2),
        encoding="utf-8",
    )


def clear_cache() -> int:
    """Delete all cached responses. Returns number of files deleted."""
    cache_dir = _cache_dir()
    if not cache_dir.exists():
        return 0
    count = 0
    for f in cache_dir.glob("*.json"):
        f.unlink()
        count += 1
    return count
