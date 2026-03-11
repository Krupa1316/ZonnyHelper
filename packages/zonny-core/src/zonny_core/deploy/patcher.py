"""DiagnosisEngine — AI-powered error classifier and config patcher.

Implements Condition 3 (deployment error → patch + retry) and
Condition 4 (development error → stop retrying, report to developer).

Two public functions:

    diagnosis = classify_and_diagnose(log, llm)
    applied   = apply_patch(diagnosis.patch, deploy_dir)

Error classes:
    "deployment"  — infra/config problem; patching the generated config and
                    retrying can fix it.
    "development" — bug in the application source code; retrying is pointless,
                    the developer must fix the code.
    "unknown"     — cannot determine; no patch is attempted, explanation only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PatchSuggestion:
    """A targeted edit to one of the generated config files."""

    file: str          # e.g. "Dockerfile", "fly.toml", "docker-compose.yml"
    description: str   # human-readable explanation of the change
    old_snippet: str   # text to locate in the file (empty → append-only patch)
    new_snippet: str   # replacement (or appended) text


@dataclass
class DiagnosisResult:
    """Structured output from the AI error classifier."""

    error_class: str                         # "deployment" | "development" | "unknown"
    explanation: str                         # plain-English explanation
    fix_suggestion: str                      # what the developer should do
    patch: PatchSuggestion | None = field(default=None)  # only for deployment errors


# ── System prompt ──────────────────────────────────────────────────────────────

_DIAGNOSE_SYSTEM = """\
You are a deployment error classifier. Given an error log from a failed
deployment or health check, you must:

1. Classify the error:
   - "deployment" — the problem is in the infrastructure config (Docker, k8s,
     cloud platform, ports, memory, missing tools, wrong image, missing env var,
     database connection). Retrying with a patched config CAN fix this.
   - "development" — the problem is in the application source code itself
     (syntax errors, import errors, runtime crashes, logic bugs, missing
     dependencies in the codebase). Retrying will NOT fix this.
   - "unknown" — cannot determine with confidence.

2. Write a plain-English explanation.

3. If error_class == "development": write a specific fix_suggestion for the
   developer, including the file and line number if visible in the log.

4. If error_class == "deployment": provide a PatchSuggestion with the exact
   text to find and replace in the generated config file.

Classification rules (strict, first match wins):
  SyntaxError, IndentationError in app source files          → "development"
  NameError, AttributeError, TypeError, ValueError            → "development"
  ImportError / ModuleNotFoundError                           → "development"
  HTTP 500 returned by the running application                → "development"
  NullPointerException / SegmentationFault in app code        → "development"
  OOMKilled, port conflict, image pull failure                → "deployment"
  Missing env var / secret                                    → "deployment"
  Database connection refused                                 → "deployment"
  Permission denied (file / socket)                          → "deployment"
  Container / pod failed to start (platform error)           → "deployment"
  Unknown pattern                                             → "unknown"

Output ONLY valid JSON — no markdown, no prose:
{
  "error_class": "deployment" | "development" | "unknown",
  "explanation": "<1-3 sentences>",
  "fix_suggestion": "<what the developer should do — filled for dev + unknown>",
  "patch": {
    "file": "<filename inside the deploy dir, e.g. Dockerfile>",
    "description": "<one sentence describing the change>",
    "old_snippet": "<exact text to replace, or empty string for append-only>",
    "new_snippet": "<replacement or appended text>"
  }
}

Important: set "patch" to null (not the object) when error_class is not "deployment".
"""


def _diagnose_prompt(log: str) -> str:
    truncated = log[:4000] + ("\n…[truncated]" if len(log) > 4000 else "")
    return f"Error log:\n\n{truncated}\n\nClassify and diagnose this error."


# ── Public API ─────────────────────────────────────────────────────────────────

def classify_and_diagnose(log: str, llm: object) -> DiagnosisResult:
    """Call *llm* to classify *log* and produce a :class:`DiagnosisResult`.

    Falls back to ``error_class="unknown"`` on any LLM or parsing failure
    so the retry loop can handle it gracefully.

    Args:
        log: The raw error output from the deployment runner or health check.
        llm: Any object that implements ``.generate(prompt, system, max_tokens)``
             — i.e. a :class:`BaseLLMProvider` instance.

    Returns:
        A :class:`DiagnosisResult` with ``error_class``, ``explanation``,
        ``fix_suggestion``, and optionally a ``patch``.
    """
    try:
        raw = llm.generate(_diagnose_prompt(log), _DIAGNOSE_SYSTEM, max_tokens=1024)  # type: ignore[union-attr]

        # Strip optional markdown fences
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("```").strip()
        data = json.loads(clean)

        patch: PatchSuggestion | None = None
        raw_patch = data.get("patch")
        if isinstance(raw_patch, dict):
            patch = PatchSuggestion(
                file=raw_patch.get("file", ""),
                description=raw_patch.get("description", ""),
                old_snippet=raw_patch.get("old_snippet", ""),
                new_snippet=raw_patch.get("new_snippet", ""),
            )

        return DiagnosisResult(
            error_class=data.get("error_class", "unknown"),
            explanation=data.get("explanation", ""),
            fix_suggestion=data.get("fix_suggestion", ""),
            patch=patch,
        )

    except Exception as exc:  # noqa: BLE001
        return DiagnosisResult(
            error_class="unknown",
            explanation=f"AI diagnosis failed: {exc}",
            fix_suggestion=(
                "Inspect the error log manually. "
                "Run [bold]zonny deploy diagnose[/bold] for an interactive AI analysis."
            ),
        )


def apply_patch(suggestion: PatchSuggestion, deploy_dir: Path) -> bool:
    """Apply a :class:`PatchSuggestion` to a file inside *deploy_dir*.

    Two modes:

    * **Replace** — ``old_snippet`` is non-empty and found in the file:
      replaces the first occurrence with ``new_snippet``.
    * **Append** — ``old_snippet`` is empty: appends ``new_snippet`` to the
      end of the file.

    Args:
        suggestion:  The patch to apply.
        deploy_dir:  Directory that contains the generated config files.

    Returns:
        ``True`` if the file was successfully modified, ``False`` otherwise
        (file not found, snippet not found, etc.).
    """
    target = deploy_dir / suggestion.file
    if not target.exists():
        return False

    content = target.read_text(encoding="utf-8")

    if suggestion.old_snippet and suggestion.old_snippet in content:
        new_content = content.replace(suggestion.old_snippet, suggestion.new_snippet, 1)
        target.write_text(new_content, encoding="utf-8")
        return True

    if not suggestion.old_snippet and suggestion.new_snippet:
        target.write_text(content.rstrip() + "\n" + suggestion.new_snippet + "\n", encoding="utf-8")
        return True

    return False  # old_snippet specified but not found
