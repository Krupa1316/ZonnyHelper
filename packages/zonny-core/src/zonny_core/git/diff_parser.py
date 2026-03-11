"""Git diff parser for zonny-helper.

Converts raw ``git diff`` output into structured DiffFile objects that
commands can inspect, summarise, and safely truncate before sending to LLMs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class DiffFile:
    """Structured representation of a single file in a git diff."""

    path: str
    """Relative path of the changed file (b-side path after rename)."""

    additions: int = 0
    """Number of lines added (lines starting with '+' excluding header)."""

    deletions: int = 0
    """Number of lines deleted (lines starting with '-' excluding header)."""

    hunks: list[str] = field(default_factory=list)
    """Raw hunk text blocks (from @@ ... @@ onwards)."""

    @property
    def raw(self) -> str:
        """Return the combined hunk text for this file."""
        return "\n".join(self.hunks)


# â”€â”€ Internal helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Matches the "diff --git a/<path> b/<path>" header line.
_DIFF_HEADER_RE = re.compile(r"^diff --git a/.+ b/(.+)$")
# Matches hunk opening lines: @@ -l,s +l,s @@ ...
_HUNK_HEADER_RE = re.compile(r"^@@ ")


def _parse_path(header_line: str) -> str:
    """Extract the b-side path from a 'diff --git' header line."""
    m = _DIFF_HEADER_RE.match(header_line)
    if m:
        return m.group(1)
    # Fallback: just return the whole line
    return header_line


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def parse_diff(raw: str) -> list[DiffFile]:
    """Parse raw ``git diff`` text into a list of :class:`DiffFile` objects.

    Parameters
    ----------
    raw:
        The full output of a ``git diff`` (or ``git diff --cached``) command.

    Returns
    -------
    list[DiffFile]
        One object per changed file, with addition/deletion counts and raw
        hunk text.
    """
    if not raw or not raw.strip():
        return []

    files: list[DiffFile] = []
    current: DiffFile | None = None
    current_hunk_lines: list[str] = []

    def _flush_hunk() -> None:
        if current is not None and current_hunk_lines:
            current.hunks.append("\n".join(current_hunk_lines))
            current_hunk_lines.clear()

    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        if _DIFF_HEADER_RE.match(line):
            # Flush any in-progress hunk, then start a new file
            _flush_hunk()
            current = DiffFile(path=_parse_path(line))
            files.append(current)
            current_hunk_lines.clear()

        elif current is not None:
            if _HUNK_HEADER_RE.match(line):
                # Start a new hunk â€” flush the previous one if any
                _flush_hunk()
                current_hunk_lines.append(line)
            elif current_hunk_lines:
                # We are inside a hunk body
                current_hunk_lines.append(line)
                if line.startswith("+") and not line.startswith("+++"):
                    current.additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    current.deletions += 1
            # Lines between the diff header and the first @@ (index lines,
            # --- a/path, +++ b/path) are intentionally skipped

        i += 1

    _flush_hunk()
    return files


def diff_stats(files: list[DiffFile]) -> dict[str, int]:
    """Compute aggregate statistics across a list of DiffFile objects.

    Parameters
    ----------
    files:
        A list returned by :func:`parse_diff`.

    Returns
    -------
    dict
        Keys: ``files_changed``, ``additions``, ``deletions``.
    """
    return {
        "files_changed": len(files),
        "additions": sum(f.additions for f in files),
        "deletions": sum(f.deletions for f in files),
    }


def truncate_diff(raw: str, max_chars: int = 60_000) -> str:
    """Truncate a raw git diff so it fits within an LLM context window.

    The algorithm keeps complete file sections from the start of the diff,
    truncating at a ``diff --git`` boundary when the limit is reached so the
    LLM always receives well-formed diff hunks.

    Parameters
    ----------
    raw:
        Raw diff text.
    max_chars:
        Maximum number of characters to return (default: 60 000, safe for
        ~16 k-token context windows).

    Returns
    -------
    str
        The (possibly truncated) diff.  If truncation occurred a notice is
        appended at the end.
    """
    if len(raw) <= max_chars:
        return raw

    # Walk through diff header positions and cut at the last safe boundary.
    cutoff = 0
    for m in re.finditer(r"^diff --git ", raw, flags=re.MULTILINE):
        if m.start() > max_chars:
            break
        cutoff = m.start()

    if cutoff == 0:
        # Single enormous file â€” just hard-truncate with a notice
        return raw[:max_chars] + "\n\n[... diff truncated due to size ...]"

    truncated = raw[:cutoff]
    original_file_count = len(re.findall(r"^diff --git ", raw, flags=re.MULTILINE))
    kept_file_count = len(re.findall(r"^diff --git ", truncated, flags=re.MULTILINE))
    skipped = original_file_count - kept_file_count

    if skipped > 0:
        truncated += (
            f"\n\n[... diff truncated: {skipped} file(s) omitted to fit LLM context ...]"
        )
    return truncated
