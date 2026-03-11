"""Git utility functions for zonny-helper.

Thin subprocess wrappers around commonly-used git commands.
All functions raise GitError on non-zero exit codes.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from zonny_core.exceptions import GitError


def run_git(args: list[str], cwd: Optional[Path] = None) -> str:
    """Run a git command and return stdout as a string.

    Parameters
    ----------
    args:
        Arguments to pass after 'git', e.g. ['diff', '--cached'].
    cwd:
        Working directory; defaults to current directory.

    Raises
    ------
    GitError
        If the command exits with a non-zero return code.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def is_git_repo(cwd: Optional[Path] = None) -> bool:
    """Return True if the current (or given) directory is inside a git repo."""
    try:
        run_git(["rev-parse", "--git-dir"], cwd=cwd)
        return True
    except GitError:
        return False


def get_staged_diff(cwd: Optional[Path] = None) -> str:
    """Return the diff of staged (cached) changes."""
    return run_git(["diff", "--cached"], cwd=cwd)


def get_branch_diff(base: str = "main", cwd: Optional[Path] = None) -> str:
    """Return the diff between the given base branch and HEAD."""
    return run_git(["diff", f"{base}...HEAD"], cwd=cwd)


def get_log(
    from_ref: str = "",
    to_ref: str = "HEAD",
    cwd: Optional[Path] = None,
) -> str:
    """Return the git log (oneline) for the given range."""
    args = ["log", "--oneline"]
    if from_ref:
        args.append(f"{from_ref}..{to_ref}")
    return run_git(args, cwd=cwd)


def get_current_branch(cwd: Optional[Path] = None) -> str:
    """Return the name of the current git branch."""
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).strip()


def get_root(cwd: Optional[Path] = None) -> Path:
    """Return the root directory of the git repository."""
    root = run_git(["rev-parse", "--show-toplevel"], cwd=cwd).strip()
    return Path(root)
