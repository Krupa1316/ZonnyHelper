"""Unit tests for git/commands.py (Phase 2 — full implementations).

All LLM calls are mocked using MockLLMProvider. Git subprocess calls are
patched in-memory so no real git operations happen.

Note: Typer's CliRunner merges stdout and stderr into result.output, so
error and warning messages are checked in result.output.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tests.conftest import MockLLMProvider
from zonny_ai.git.commands import app

runner = CliRunner()

# ── Helpers ────────────────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b[()][0-9A-Z]|\x1b[>=?]|\r")


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes and non-printable control chars from Rich output."""
    cleaned = _ANSI_RE.sub("", text)
    # Remove any remaining non-printable control chars except newlines/tabs
    return "".join(c for c in cleaned if c >= " " or c in "\n\t")


def _extract_json(output: str) -> dict:
    """Extract and parse the first JSON object from (possibly ANSI-coloured) CLI output.

    Rich's Syntax renderer pads each line to terminal width with trailing spaces.
    We strip those before parsing.
    """
    clean = _strip_ansi(output)
    # Strip trailing whitespace from each line (Rich pads to terminal width)
    clean = "\n".join(line.rstrip() for line in clean.splitlines())
    start = clean.find("{")
    end = clean.rfind("}") + 1
    return json.loads(clean[start:end])


# ── Sample data ────────────────────────────────────────────────────────────────

SAMPLE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
index 1234567..abcdefg 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 def hello():
-    print("hi")
+    print("hello")
+    return None
"""

SAMPLE_LOG = """\
abc1234 feat(auth): add OAuth2 login
def5678 fix(payments): handle null card number
ghi9012 chore: update dependencies
"""

CI_LOG_CONTENT = """\
ERROR: ModuleNotFoundError: No module named 'requests'
  File "app.py", line 5, in <module>
    import requests
Build FAILED with exit code 1
"""


def _make_mock_llm(response: str = "mocked LLM response") -> MockLLMProvider:
    return MockLLMProvider(responses=[response])


def _patch_llm(mock_llm: MockLLMProvider):
    """Patch get_provider in the commands module to return mock_llm."""
    return patch("zonny_ai.git.commands.get_provider", return_value=mock_llm)


def _patch_git_repo(is_repo: bool = True):
    return patch("zonny_ai.git.commands.is_git_repo", return_value=is_repo)


def _patch_staged_diff(diff: str = SAMPLE_DIFF):
    return patch("zonny_ai.git.commands.get_staged_diff", return_value=diff)


def _patch_branch_diff(diff: str = SAMPLE_DIFF):
    return patch("zonny_ai.git.commands.get_branch_diff", return_value=diff)


def _patch_git_log(log: str = SAMPLE_LOG):
    return patch("zonny_ai.git.commands.get_log", return_value=log)


# ── zonny git commit ──────────────────────────────────────────────────────────


class TestCommitCommand:
    def test_not_git_repo_exits_with_error(self) -> None:
        with _patch_git_repo(False):
            result = runner.invoke(app, ["commit"])
        assert result.exit_code == 1
        assert "Not a git repository" in result.output

    def test_nothing_staged_exits_with_error(self) -> None:
        with _patch_git_repo(), _patch_staged_diff(""):
            result = runner.invoke(app, ["commit"])
        assert result.exit_code == 1
        assert "No staged changes" in result.output

    def test_dry_run_shows_message(self) -> None:
        mock_llm = _make_mock_llm("feat(foo): add hello function")
        with _patch_git_repo(), _patch_staged_diff(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["commit", "--dry-run"])
        assert result.exit_code == 0
        assert "feat(foo): add hello function" in result.output

    def test_default_no_execute_shows_tip(self) -> None:
        mock_llm = _make_mock_llm("fix: patch something")
        with _patch_git_repo(), _patch_staged_diff(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["commit"])
        assert result.exit_code == 0
        assert "fix: patch something" in result.output
        # Should print tip about --execute
        assert "--execute" in result.output

    def test_json_output_contains_commit_message_key(self) -> None:
        mock_llm = _make_mock_llm("chore: bump version")
        with _patch_git_repo(), _patch_staged_diff(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["commit", "--json"])
        assert result.exit_code == 0
        data = _extract_json(result.output)
        assert "commit_message" in data
        assert data["commit_message"] == "chore: bump version"

    def test_json_output_contains_provider(self) -> None:
        mock_llm = _make_mock_llm("refactor: clean up")
        with _patch_git_repo(), _patch_staged_diff(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["commit", "--json"])
        data = _extract_json(result.output)
        assert "provider" in data

    def test_execute_runs_git_commit(self) -> None:
        mock_llm = _make_mock_llm("feat: new feature")
        with (
            _patch_git_repo(),
            _patch_staged_diff(),
            _patch_llm(mock_llm),
            patch("zonny_ai.git.commands.run_git") as mock_run,
        ):
            result = runner.invoke(app, ["commit", "--execute"])
        assert result.exit_code == 0
        mock_run.assert_called_once_with(["commit", "-m", "feat: new feature"])

    def test_dry_run_does_not_execute(self) -> None:
        mock_llm = _make_mock_llm("feat: new feature")
        with (
            _patch_git_repo(),
            _patch_staged_diff(),
            _patch_llm(mock_llm),
            patch("zonny_ai.git.commands.run_git") as mock_run,
        ):
            result = runner.invoke(app, ["commit", "--dry-run", "--execute"])
        assert result.exit_code == 0
        mock_run.assert_not_called()

    def test_type_and_scope_passed_to_prompt(self) -> None:
        mock_llm = _make_mock_llm("feat(payments): add stripe integration")
        with (
            _patch_git_repo(),
            _patch_staged_diff(),
            _patch_llm(mock_llm),
            patch("zonny_ai.git.commands.commit_prompt") as mock_prompt,
        ):
            mock_prompt.return_value = ("system", "user prompt")
            runner.invoke(app, ["commit", "--type", "feat", "--scope", "payments", "--dry-run"])
        mock_prompt.assert_called_once_with(SAMPLE_DIFF, "feat", "payments")

    def test_llm_calls_are_recorded(self) -> None:
        mock_llm = _make_mock_llm("docs: update readme")
        with _patch_git_repo(), _patch_staged_diff(), _patch_llm(mock_llm):
            runner.invoke(app, ["commit", "--dry-run"])
        assert len(mock_llm.calls) == 1


# ── zonny git pr ──────────────────────────────────────────────────────────────


class TestPrCommand:
    def test_not_git_repo_exits_with_error(self) -> None:
        with _patch_git_repo(False):
            result = runner.invoke(app, ["pr"])
        assert result.exit_code == 1
        assert "Not a git repository" in result.output

    def test_empty_branch_diff_exits_cleanly(self) -> None:
        with _patch_git_repo(), _patch_branch_diff(""):
            result = runner.invoke(app, ["pr"])
        assert result.exit_code == 0
        # Should warn but not error
        assert "No diff" in result.output

    def test_pr_generates_description(self) -> None:
        mock_llm = _make_mock_llm("## Summary\nAdds hello function.\n## Changes\n- New func")
        with _patch_git_repo(), _patch_branch_diff(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["pr"])
        assert result.exit_code == 0
        assert "## Summary" in result.output

    def test_pr_json_output(self) -> None:
        mock_llm = _make_mock_llm("## Summary\nPR description here.")
        with _patch_git_repo(), _patch_branch_diff(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["pr", "--json"])
        assert result.exit_code == 0
        data = _extract_json(result.output)
        assert "pr_description" in data
        assert "base" in data

    def test_pr_missing_template_file_errors(self) -> None:
        mock_llm = _make_mock_llm("desc")
        with _patch_git_repo(), _patch_branch_diff(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["pr", "--template", "nonexistent_template.md"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_pr_with_valid_template(self, tmp_path: Path) -> None:
        template = tmp_path / "pr_template.md"
        template.write_text("## My Template\n- [ ] Tests added")
        mock_llm = _make_mock_llm("description from template")
        with _patch_git_repo(), _patch_branch_diff(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["pr", "--template", str(template)])
        assert result.exit_code == 0
        assert len(mock_llm.calls) == 1
        # Template content should be in the prompt
        assert "My Template" in mock_llm.calls[0]["prompt"]


# ── zonny git changelog ───────────────────────────────────────────────────────


class TestChangelogCommand:
    def test_not_git_repo_exits_with_error(self) -> None:
        with _patch_git_repo(False):
            result = runner.invoke(app, ["changelog"])
        assert result.exit_code == 1

    def test_empty_log_exits_cleanly(self) -> None:
        with _patch_git_repo(), _patch_git_log(""):
            result = runner.invoke(app, ["changelog"])
        assert result.exit_code == 0

    def test_generates_changelog(self) -> None:
        mock_llm = _make_mock_llm("### Features\n- Add OAuth2\n\n### Bug Fixes\n- Fix card null")
        with _patch_git_repo(), _patch_git_log(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["changelog"])
        assert result.exit_code == 0
        assert "### Features" in result.output

    def test_json_format_output(self) -> None:
        mock_llm = _make_mock_llm("changelog content")
        with _patch_git_repo(), _patch_git_log(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["changelog", "--format", "json"])
        data = _extract_json(result.output)
        assert "changelog" in data
        assert "from_ref" in data
        assert "to_ref" in data

    def test_writes_to_output_file(self, tmp_path: Path) -> None:
        out_file = tmp_path / "CHANGELOG.md"
        mock_llm = _make_mock_llm("### Features\n- stuff")
        with _patch_git_repo(), _patch_git_log(), _patch_llm(mock_llm):
            result = runner.invoke(app, ["changelog", "--output", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        assert "### Features" in out_file.read_text()

    def test_from_ref_passed_to_git_log(self) -> None:
        mock_llm = _make_mock_llm("content")
        with (
            _patch_git_repo(),
            _patch_llm(mock_llm),
            patch("zonny_ai.git.commands.get_log") as mock_log,
        ):
            mock_log.return_value = SAMPLE_LOG
            runner.invoke(app, ["changelog", "--from", "v0.1.0"])
        mock_log.assert_called_once_with("v0.1.0", "HEAD")


# ── zonny git whybroke ────────────────────────────────────────────────────────


class TestWhybrokeCommand:
    def test_no_log_flag_errors(self) -> None:
        result = runner.invoke(app, ["whybroke"])
        assert result.exit_code == 1
        assert "--log" in result.output

    def test_missing_log_file_errors(self) -> None:
        result = runner.invoke(app, ["whybroke", "--log", "nonexistent_ci.log"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_empty_log_file_exits(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ci.log"
        log_file.write_text("")
        result = runner.invoke(app, ["whybroke", "--log", str(log_file)])
        assert result.exit_code == 1

    def test_generates_diagnosis(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ci.log"
        log_file.write_text(CI_LOG_CONTENT)
        diagnosis = "**Root Cause:** Missing package\n**Evidence:** line 1\n**Suggested Fix:** pip install requests"
        mock_llm = _make_mock_llm(diagnosis)
        with _patch_llm(mock_llm):
            result = runner.invoke(app, ["whybroke", "--log", str(log_file)])
        assert result.exit_code == 0
        assert "Root Cause" in result.output

    def test_json_output(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ci.log"
        log_file.write_text(CI_LOG_CONTENT)
        mock_llm = _make_mock_llm("Root cause: missing dep")
        with _patch_llm(mock_llm):
            result = runner.invoke(app, ["whybroke", "--log", str(log_file), "--json"])
        assert result.exit_code == 0
        # Rich's Syntax renderer may add control chars inside values, so we check
        # for key presence as strings rather than parsing the full JSON.
        clean_output = _strip_ansi(result.output)
        assert '"diagnosis"' in clean_output
        assert '"log_file"' in clean_output
        assert '"ci"' in clean_output

    def test_ci_label_in_prompt(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ci.log"
        log_file.write_text(CI_LOG_CONTENT)
        mock_llm = _make_mock_llm("diagnosis")
        with _patch_llm(mock_llm):
            runner.invoke(app, ["whybroke", "--log", str(log_file), "--ci", "jenkins"])
        # The CI label should appear in the prompt
        assert "jenkins" in mock_llm.calls[0]["prompt"]

    def test_diff_flag_includes_staged_diff(self, tmp_path: Path) -> None:
        log_file = tmp_path / "ci.log"
        log_file.write_text(CI_LOG_CONTENT)
        mock_llm = _make_mock_llm("diagnosis with diff")
        with (
            _patch_llm(mock_llm),
            _patch_git_repo(),
            _patch_staged_diff(SAMPLE_DIFF),
        ):
            result = runner.invoke(app, ["whybroke", "--log", str(log_file), "--diff"])
        assert result.exit_code == 0
        assert len(mock_llm.calls) == 1
