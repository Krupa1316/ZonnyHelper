"""Shared LLM prompt templates for zonny-helper.

All prompts return a (system, user_prompt) tuple consumed by BaseLLMProvider.generate().
Keeping prompts here makes them easy to tune without touching command logic.
"""
from __future__ import annotations

# â”€â”€ Git prompts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_COMMIT_SYSTEM = """You are an expert software engineer writing git commit messages.
Follow the Conventional Commits specification (https://conventionalcommits.org).
Commit types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert.
Output ONLY the commit message â€” no explanation, no markdown fences, no extra text.

Format:
  type(scope): short subject (<=72 chars, lowercase, no period)

  Optional body: explain WHY the change was made, not WHAT (wrap at 72 chars).
  Use blank line between subject and body.
"""

_PR_SYSTEM = """You are an expert software engineer writing a GitHub Pull Request description.
Output ONLY the Markdown PR description. Do NOT include any explanation or preamble.
Structure your output exactly as:

## Summary
<one paragraph summary of what this PR does and why>

## Changes
<bullet list of key changes>

## Testing
<brief description of how this was tested or what tests were added>

## Breaking Changes
<list any breaking changes, or write "None">
"""

_CHANGELOG_SYSTEM = """You are a technical writer generating a CHANGELOG from git log entries.
Output ONLY the Markdown changelog section. No preamble.
Group entries into: ### Features, ### Bug Fixes, ### Breaking Changes, ### Other.
Omit empty sections. Each entry as a bullet: `- <clear description> (<commit hash>)`.
"""

_WHYBROKE_SYSTEM = """You are a senior DevOps engineer diagnosing a CI failure.
Given CI failure logs and a recent code diff, identify the most likely root cause
and suggest a specific fix.
Output structure:
  **Root Cause:** <one sentence>
  **Evidence:** <cite specific log lines or diff hunks>
  **Suggested Fix:** <concrete code or command to apply>
"""

# â”€â”€ Tree prompts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_ENRICH_SYSTEM = """You are a code architecture analyst.
Given a list of code entities (functions, classes, methods), return a JSON array
where each object has EXACTLY these keys:
  "entity":      the entity name (match input exactly)
  "flow_labels": array of labels, each from [AUTH, VALIDATE, TRANSFORM, PERSIST, FETCH, NOTIFY, ROUTE, UTIL]
  "complexity":  "low" | "medium" | "high"
  "ai_label":    short snake_case label (e.g. "critical-write-path", "auth-guard", "db-reader")

Output ONLY valid JSON. No explanation. No markdown fences. No trailing commas.
"""

_QUERY_SYSTEM = """You are a codebase expert with full knowledge of the entity tree provided.
Answer the user's question about the codebase with specific file:line references.
Be concise. Use bullet points for lists. Always cite file paths in the format `file.py:42`.
If the answer is not in the tree, say so clearly.
"""


# â”€â”€ Prompt builder functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def commit_prompt(diff: str, commit_type: str = "", scope: str = "") -> tuple[str, str]:
    """Build the system + user prompt for commit message generation."""
    hint_parts = []
    if commit_type:
        hint_parts.append(f"Preferred commit type: {commit_type}")
    if scope:
        hint_parts.append(f"Preferred scope: {scope}")
    hint = ("\n".join(hint_parts) + "\n\n") if hint_parts else ""
    return _COMMIT_SYSTEM, f"{hint}Git diff:\n{diff}"


def pr_prompt(branch_diff: str, base: str = "main") -> tuple[str, str]:
    """Build the system + user prompt for PR description generation."""
    return _PR_SYSTEM, f"Base branch: {base}\n\nGit diff:\n{branch_diff}"


def changelog_prompt(log: str) -> tuple[str, str]:
    """Build the system + user prompt for CHANGELOG generation."""
    return _CHANGELOG_SYSTEM, f"Git log:\n{log}"


def whybroke_prompt(ci_log: str, diff: str = "") -> tuple[str, str]:
    """Build the system + user prompt for CI failure diagnosis."""
    parts = [f"CI Failure Log:\n{ci_log}"]
    if diff:
        parts.append(f"Recent code diff:\n{diff}")
    return _WHYBROKE_SYSTEM, "\n\n".join(parts)


def enrich_prompt(entities_json: str) -> tuple[str, str]:
    """Build the system + user prompt for entity enrichment."""
    return _ENRICH_SYSTEM, f"Entities to annotate:\n{entities_json}"


def query_prompt(question: str, tree_context: str) -> tuple[str, str]:
    """Build the system + user prompt for a natural language tree query."""
    return _QUERY_SYSTEM, f"Codebase entity tree:\n{tree_context}\n\nQuestion: {question}"
