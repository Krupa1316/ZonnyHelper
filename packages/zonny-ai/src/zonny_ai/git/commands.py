"""Git workflow commands â€” Typer sub-application (Phase 2 â€” Full Implementation).

Four AI-powered commands that automate the most repetitive parts of a git
workflow:

  zonny git commit     â€” Generate a Conventional Commit message from staged diff
  zonny git pr         â€” Generate a GitHub PR description from branch diff
  zonny git changelog  â€” Generate a CHANGELOG section from git log
  zonny git whybroke   â€” Diagnose a CI failure from logs + recent diff
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from zonny_core.config.loader import load_config
from zonny_core.exceptions import GitError, LLMError, LLMProviderNotAvailable, ZonnyConfigError
from zonny_core.git.diff_parser import truncate_diff
from zonny_ai.llm.prompts import (
    changelog_prompt,
    commit_prompt,
    pr_prompt,
    whybroke_prompt,
)
from zonny_ai.llm.router import get_provider
from zonny_core.utils.git_utils import (
    get_branch_diff,
    get_log,
    get_staged_diff,
    is_git_repo,
    run_git,
)
from zonny_core.utils.output import (
    console,
    error,
    print_json,
    print_panel,
    success,
    warn,
)

app = typer.Typer(
    name="git",
    help="AI-powered git workflow automation.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

err_console = Console(stderr=True)


# â”€â”€ Shared helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _guard_git_repo() -> None:
    """Exit with an error if not inside a git repository."""
    if not is_git_repo():
        error("Not a git repository. Run this command from inside a git repo.")
        raise typer.Exit(1)


def _get_llm(provider_override: str | None):  # type: ignore[return]
    """Load config and return the configured LLM provider."""
    try:
        overrides = {"llm": {"provider": provider_override}} if provider_override else {}
        config = load_config(overrides)
        provider = get_provider(config, provider_override)
        if not provider.available():
            error(
                f"Provider '{provider.name()}' is not available. "
                "Check your API key or that Ollama is running."
            )
            raise typer.Exit(1)
        return provider
    except ZonnyConfigError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc


def _run_llm(llm, prompt: str, system: str, label: str) -> str:
    """Call the LLM and return the response, with user-friendly error handling."""
    try:
        with console.status(f"[bold green]{label}...[/bold green]"):
            return llm.generate(prompt, system)
    except (LLMError, LLMProviderNotAvailable) as exc:
        error(f"LLM error: {exc}")
        raise typer.Exit(1) from exc
    except Exception as exc:  # noqa: BLE001
        error(f"Unexpected error calling LLM: {exc}")
        raise typer.Exit(1) from exc


# â”€â”€ Commands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@app.command()
def commit(
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n",
        help="Show the generated message but do NOT run `git commit`.",
    ),
    execute: bool = typer.Option(
        False, "--execute", "-e",
        help="Automatically run `git commit -m <message>` after generating.",
    ),
    type_: str = typer.Option(
        "", "--type", "-t",
        help="Commit type hint (feat, fix, chore, docs, refactor, â€¦).",
    ),
    scope: str = typer.Option(
        "", "--scope", "-s",
        help="Optional scope hint (e.g. 'payments', 'auth').",
    ),
    provider: str | None = typer.Option(  # noqa: UP007
        None, "--provider", "-p",
        help="LLM provider override (anthropic | openai | gemini | ollama).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Generate a [bold]Conventional Commit[/bold] message from staged changes.

    Stage your files first with `git add`, then run this command.
    Use --dry-run to preview the message without committing.
    Use --execute to automatically run `git commit` after generating.
    """
    _guard_git_repo()

    # 1. Get staged diff
    try:
        diff = get_staged_diff()
    except GitError as exc:
        error(f"Could not read staged diff: {exc}")
        raise typer.Exit(1) from exc

    if not diff.strip():
        error("No staged changes found. Run `git add <files>` first.")
        raise typer.Exit(1)

    # 2. Truncate to LLM context window
    diff = truncate_diff(diff)
    if len(diff) < len(diff):
        warn("Diff was truncated to fit the LLM context window.")

    # 3. Get LLM provider
    llm = _get_llm(provider)

    # 4. Generate commit message
    system, prompt = commit_prompt(diff, type_, scope)
    message = _run_llm(llm, prompt, system, "Generating commit message")

    # 5. Display result
    if json_output:
        print_json({"commit_message": message, "provider": llm.name()})
    else:
        print_panel(message, title="Suggested Commit Message", border_style="green")

    # 6. Execute if requested (and not a dry-run)
    if not dry_run and execute:
        try:
            run_git(["commit", "-m", message])
            success("Committed successfully.")
        except GitError as exc:
            error(f"git commit failed: {exc}")
            raise typer.Exit(1) from exc
    elif not dry_run and not execute:
        console.print(
            "\n[dim]Tip: run with [bold]--execute[/bold] to automatically commit,"
            " or copy the message above.[/dim]"
        )


@app.command()
def pr(
    base: str = typer.Option(
        "main", "--base", "-b",
        help="Base branch to diff against (default: main).",
    ),
    template: str | None = typer.Option(  # noqa: UP007
        None, "--template",
        help="Path to a PR template file whose content is appended to the prompt.",
    ),
    provider: str | None = typer.Option(  # noqa: UP007
        None, "--provider", "-p",
        help="LLM provider override.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Generate a [bold]GitHub Pull Request[/bold] description from the branch diff.

    Compares the current branch against BASE and produces a structured PR
    description with Summary, Changes, Testing, and Breaking Changes sections.
    """
    _guard_git_repo()

    # 1. Get branch diff
    try:
        branch_diff = get_branch_diff(base)
    except GitError as exc:
        error(f"Could not get branch diff: {exc}")
        raise typer.Exit(1) from exc

    if not branch_diff.strip():
        warn(f"No diff found between current branch and '{base}'. Nothing to generate.")
        raise typer.Exit(0)

    branch_diff = truncate_diff(branch_diff)

    # 2. Optionally load template
    template_text = ""
    if template:
        tp = Path(template)
        if not tp.exists():
            error(f"Template file not found: {template}")
            raise typer.Exit(1)
        template_text = tp.read_text(encoding="utf-8")

    # 3. Generate PR description
    llm = _get_llm(provider)
    system, prompt_text = pr_prompt(branch_diff, base)
    if template_text:
        prompt_text += f"\n\nPlease follow this PR template structure:\n{template_text}"

    description = _run_llm(llm, prompt_text, system, "Generating PR description")

    # 4. Display
    if json_output:
        print_json({"pr_description": description, "base": base, "provider": llm.name()})
    else:
        print_panel(description, title=f"PR Description (vs {base})", border_style="blue")


@app.command()
def changelog(
    from_ref: str = typer.Option(
        "", "--from",
        help="Start ref (tag or commit SHA, e.g. v0.1.0). Defaults to all commits.",
    ),
    to_ref: str = typer.Option(
        "HEAD", "--to",
        help="End ref (default: HEAD).",
    ),
    format_: str = typer.Option(
        "md", "--format", "-f",
        help="Output format: [bold]md[/bold] (default) | [bold]json[/bold].",
    ),
    output: str | None = typer.Option(  # noqa: UP007
        None, "--output", "-o",
        help="Write changelog to this file instead of printing to stdout.",
    ),
    provider: str | None = typer.Option(  # noqa: UP007
        None, "--provider", "-p",
        help="LLM provider override.",
    ),
) -> None:
    """Generate a [bold]CHANGELOG[/bold] section from git log entries.

    Groups commits into Features, Bug Fixes, Breaking Changes, and Other.
    Use --from <tag> to generate a changelog since a specific release.
    """
    _guard_git_repo()

    # 1. Get commit log
    try:
        log = get_log(from_ref, to_ref)
    except GitError as exc:
        error(f"Could not get git log: {exc}")
        raise typer.Exit(1) from exc

    if not log.strip():
        ref_desc = f"from {from_ref} to {to_ref}" if from_ref else f"up to {to_ref}"
        warn(f"No commits found ({ref_desc}). Nothing to generate.")
        raise typer.Exit(0)

    # 2. Generate changelog
    llm = _get_llm(provider)
    system, prompt_text = changelog_prompt(log)
    changelog_text = _run_llm(llm, prompt_text, system, "Generating CHANGELOG")

    # 3. Output
    if format_ == "json" or (format_ == "md" and output and output.endswith(".json")):
        data = {
            "changelog": changelog_text,
            "from_ref": from_ref or "(beginning)",
            "to_ref": to_ref,
            "provider": llm.name(),
        }
        if output:
            Path(output).write_text(json.dumps(data, indent=2), encoding="utf-8")
            success(f"Changelog written to {output}")
        else:
            print_json(data)
    else:
        if output:
            Path(output).write_text(changelog_text, encoding="utf-8")
            success(f"Changelog written to {output}")
        else:
            print_panel(changelog_text, title="Generated CHANGELOG", border_style="yellow")


@app.command()
def whybroke(
    log: str | None = typer.Option(  # noqa: UP007
        None, "--log", "-l",
        help="Path to a CI log file to diagnose.",
    ),
    ci: str = typer.Option(
        "github-actions", "--ci",
        help="CI system label for context (github-actions | jenkins | circleci | â€¦).",
    ),
    include_diff: bool = typer.Option(
        False, "--diff", "-d",
        help="Append the current staged diff as additional context.",
    ),
    provider: str | None = typer.Option(  # noqa: UP007
        None, "--provider", "-p",
        help="LLM provider override.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Diagnose a [bold]CI failure[/bold] from logs and recent diff.

    Reads the CI log file and asks the LLM to identify the root cause and
    suggest a specific fix.  Use --diff to also send current staged changes.
    """
    # 1. Read CI log
    if log is None:
        error(
            "No log file specified. Use --log <path> to provide a CI log.\n"
            "  Example: zonny git whybroke --log ci_failure.log"
        )
        raise typer.Exit(1)

    log_path = Path(log)
    if not log_path.exists():
        error(f"CI log file not found: {log_path}")
        raise typer.Exit(1)

    ci_log = log_path.read_text(encoding="utf-8", errors="replace")
    if not ci_log.strip():
        warn("CI log file is empty.")
        raise typer.Exit(1)

    # Trim very long logs to keep them within LLM context
    if len(ci_log) > 40_000:
        ci_log = ci_log[-40_000:]
        warn("CI log was trimmed to the last 40 000 characters.")

    # 2. Optional: append staged diff
    diff_text = ""
    if include_diff:
        try:
            diff_text = get_staged_diff()
            diff_text = truncate_diff(diff_text, max_chars=15_000)
        except GitError:
            warn("Could not read staged diff â€” skipping diff context.")

    # 3. Generate diagnosis
    llm = _get_llm(provider)
    system, prompt_text = whybroke_prompt(ci_log, diff_text)
    # Prepend CI system context to the prompt
    prompt_text = f"CI System: {ci}\n\n{prompt_text}"

    diagnosis = _run_llm(llm, prompt_text, system, "Diagnosing CI failure")

    # 4. Display
    if json_output:
        print_json({
            "diagnosis": diagnosis,
            "log_file": str(log_path),
            "ci": ci,
            "provider": llm.name(),
        })
    else:
        print_panel(diagnosis, title=f"CI Failure Diagnosis ({ci})", border_style="red")
