"""File utility helpers for zonny-helper."""
from __future__ import annotations

import fnmatch
from pathlib import Path


def matches_any(path: Path, patterns: list[str]) -> bool:
    """Return True if any path component or the full path matches a glob pattern."""
    path_str = path.as_posix()
    for pattern in patterns:
        # Match against the full path or just the filename
        if fnmatch.fnmatch(path_str, f"**/{pattern}") or fnmatch.fnmatch(path.name, pattern):
            return True
        # Also check if any parent directory matches
        for part in path.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def find_files(
    root: Path,
    extensions: list[str],
    ignore_patterns: list[str],
    max_file_size_kb: int = 500,
    max_depth: int | None = None,
) -> list[Path]:
    """Recursively find all files matching extensions under root.

    Parameters
    ----------
    root:
        Root directory to walk.
    extensions:
        File extensions to include (with leading dot, e.g. ['.py', '.js']).
    ignore_patterns:
        Glob patterns for paths to skip.
    max_file_size_kb:
        Skip files larger than this size in kilobytes.
    max_depth:
        Maximum directory depth to recurse into (None = unlimited).

    Returns
    -------
    list[Path]
        Sorted list of matching file paths.
    """
    results: list[Path] = []
    root = root.resolve()

    def _walk(directory: Path, depth: int) -> None:
        if max_depth is not None and depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return
        for entry in entries:
            rel = entry.relative_to(root)
            if matches_any(rel, ignore_patterns):
                continue
            if entry.is_dir():
                _walk(entry, depth + 1)
            elif entry.is_file() and entry.suffix.lower() in extensions:
                size_kb = entry.stat().st_size / 1024
                if size_kb <= max_file_size_kb:
                    results.append(entry)

    _walk(root, 0)
    return results


def read_file_safe(path: Path) -> str:
    """Read a file returning its content, replacing undecodable bytes."""
    return path.read_text(encoding="utf-8", errors="replace")
