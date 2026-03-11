"""Unit tests for DiagnosisEngine / patcher (patcher.py).

Tests cover:
  - PatchSuggestion and DiagnosisResult dataclasses
  - classify_and_diagnose():
      - happy path with all three error classes
      - markdown fence stripping
      - bad JSON → unknown fallback
      - LLM exception → unknown fallback
      - long log truncation
      - patch object populated correctly
  - apply_patch():
      - replace mode (old_snippet found)
      - append mode (empty old_snippet)
      - file not found → False
      - snippet not found → False
      - multiple occurrences → only first replaced
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from zonny_core.deploy.patcher import (
    DiagnosisResult,
    PatchSuggestion,
    _diagnose_prompt,
    apply_patch,
    classify_and_diagnose,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_llm(response: str) -> MagicMock:
    llm = MagicMock()
    llm.generate.return_value = response
    return llm


def _deployment_json(**extra) -> str:
    base = {
        "error_class": "deployment",
        "explanation": "Port 8080 is already in use.",
        "fix_suggestion": "",
        "patch": {
            "file": "Dockerfile",
            "description": "Change EXPOSE port from 8080 to 8081",
            "old_snippet": "EXPOSE 8080",
            "new_snippet": "EXPOSE 8081",
        },
    }
    base.update(extra)
    return json.dumps(base)


def _dev_json(**extra) -> str:
    base = {
        "error_class": "development",
        "explanation": "ImportError: No module named 'pydantic'",
        "fix_suggestion": "Add 'pydantic' to requirements.txt",
        "patch": None,
    }
    base.update(extra)
    return json.dumps(base)


def _unknown_json(**extra) -> str:
    base = {
        "error_class": "unknown",
        "explanation": "Could not determine the error cause.",
        "fix_suggestion": "Inspect the logs manually.",
        "patch": None,
    }
    base.update(extra)
    return json.dumps(base)


# ── PatchSuggestion dataclass ──────────────────────────────────────────────────

class TestPatchSuggestion:
    def test_fields_accessible(self) -> None:
        ps = PatchSuggestion(
            file="Dockerfile",
            description="change port",
            old_snippet="EXPOSE 8080",
            new_snippet="EXPOSE 8081",
        )
        assert ps.file == "Dockerfile"
        assert ps.old_snippet == "EXPOSE 8080"
        assert ps.new_snippet == "EXPOSE 8081"


# ── DiagnosisResult dataclass ──────────────────────────────────────────────────

class TestDiagnosisResult:
    def test_no_patch_by_default(self) -> None:
        dr = DiagnosisResult(
            error_class="development",
            explanation="syntax error",
            fix_suggestion="fix the code",
        )
        assert dr.patch is None

    def test_with_patch(self) -> None:
        ps = PatchSuggestion(file="fly.toml", description="x", old_snippet="a", new_snippet="b")
        dr = DiagnosisResult(
            error_class="deployment",
            explanation="memory issue",
            fix_suggestion="",
            patch=ps,
        )
        assert dr.patch is ps


# ── classify_and_diagnose ──────────────────────────────────────────────────────

class TestClassifyAndDiagnose:
    def test_deployment_error_with_patch(self) -> None:
        llm = _mock_llm(_deployment_json())
        result = classify_and_diagnose("Bind: Address already in use", llm)
        assert result.error_class == "deployment"
        assert result.patch is not None
        assert result.patch.file == "Dockerfile"
        assert result.patch.old_snippet == "EXPOSE 8080"
        assert result.patch.new_snippet == "EXPOSE 8081"

    def test_development_error_no_patch(self) -> None:
        llm = _mock_llm(_dev_json())
        result = classify_and_diagnose("ImportError: No module named 'pydantic'", llm)
        assert result.error_class == "development"
        assert result.fix_suggestion == "Add 'pydantic' to requirements.txt"
        assert result.patch is None

    def test_unknown_error(self) -> None:
        llm = _mock_llm(_unknown_json())
        result = classify_and_diagnose("some weird error", llm)
        assert result.error_class == "unknown"
        assert result.patch is None

    def test_strips_markdown_fence(self) -> None:
        payload = "```json\n" + _dev_json() + "\n```"
        llm = _mock_llm(payload)
        result = classify_and_diagnose("error", llm)
        assert result.error_class == "development"

    def test_strips_plain_fence(self) -> None:
        payload = "```\n" + _unknown_json() + "\n```"
        llm = _mock_llm(payload)
        result = classify_and_diagnose("error", llm)
        assert result.error_class == "unknown"

    def test_bad_json_returns_unknown(self) -> None:
        llm = _mock_llm("this is not JSON at all !!!")
        result = classify_and_diagnose("error log", llm)
        assert result.error_class == "unknown"
        assert "AI diagnosis failed" in result.explanation

    def test_llm_exception_returns_unknown(self) -> None:
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("network error")
        result = classify_and_diagnose("error log", llm)
        assert result.error_class == "unknown"

    def test_missing_error_class_defaults_unknown(self) -> None:
        payload = json.dumps({"explanation": "something happened", "fix_suggestion": ""})
        llm = _mock_llm(payload)
        result = classify_and_diagnose("error", llm)
        assert result.error_class == "unknown"

    def test_explanation_is_preserved(self) -> None:
        llm = _mock_llm(_deployment_json())
        result = classify_and_diagnose("bind error", llm)
        assert "Port 8080" in result.explanation

    def test_patch_is_none_when_null_in_json(self) -> None:
        payload = json.dumps({
            "error_class": "deployment",
            "explanation": "memory crash",
            "fix_suggestion": "",
            "patch": None,
        })
        llm = _mock_llm(payload)
        result = classify_and_diagnose("OOMKilled", llm)
        assert result.patch is None

    def test_patch_fields_all_populated(self) -> None:
        llm = _mock_llm(_deployment_json())
        result = classify_and_diagnose("error", llm)
        assert result.patch is not None
        assert result.patch.description == "Change EXPOSE port from 8080 to 8081"


# ── _diagnose_prompt ──────────────────────────────────────────────────────────

class TestDiagnosePrompt:
    def test_includes_log(self) -> None:
        prompt = _diagnose_prompt("ImportError: no module named foo")
        assert "ImportError" in prompt

    def test_truncates_long_log(self) -> None:
        long_log = "a" * 5000
        prompt = _diagnose_prompt(long_log)
        assert "truncated" in prompt.lower() or len(prompt) < len(long_log) + 100

    def test_short_log_not_truncated(self) -> None:
        short = "short error message"
        prompt = _diagnose_prompt(short)
        assert "truncated" not in prompt


# ── apply_patch ───────────────────────────────────────────────────────────────

class TestApplyPatch:
    def test_replace_mode(self, tmp_path: Path) -> None:
        f = tmp_path / "Dockerfile"
        f.write_text("FROM python:3.11\nEXPOSE 8080\nCMD python main.py\n")

        ps = PatchSuggestion(
            file="Dockerfile",
            description="fix port",
            old_snippet="EXPOSE 8080",
            new_snippet="EXPOSE 8081",
        )
        result = apply_patch(ps, tmp_path)

        assert result is True
        content = f.read_text()
        assert "EXPOSE 8081" in content
        assert "EXPOSE 8080" not in content

    def test_append_mode(self, tmp_path: Path) -> None:
        f = tmp_path / "fly.toml"
        f.write_text("[build]\n  builder = \"heroku/buildpacks:20\"\n")

        ps = PatchSuggestion(
            file="fly.toml",
            description="add memory",
            old_snippet="",
            new_snippet="[vm]\n  memory = \"1gb\"",
        )
        result = apply_patch(ps, tmp_path)

        assert result is True
        content = f.read_text()
        assert "1gb" in content

    def test_file_not_found_returns_false(self, tmp_path: Path) -> None:
        ps = PatchSuggestion(
            file="nonexistent.conf",
            description="irrelevant",
            old_snippet="x",
            new_snippet="y",
        )
        result = apply_patch(ps, tmp_path)
        assert result is False

    def test_snippet_not_found_returns_false(self, tmp_path: Path) -> None:
        f = tmp_path / "docker-compose.yml"
        f.write_text("version: '3'\nservices:\n  app:\n    image: myimage\n")

        ps = PatchSuggestion(
            file="docker-compose.yml",
            description="fix port",
            old_snippet="ports:\n  - '9999:9999'",  # not in file
            new_snippet="ports:\n  - '8000:8000'",
        )
        result = apply_patch(ps, tmp_path)
        assert result is False

    def test_only_first_occurrence_replaced(self, tmp_path: Path) -> None:
        f = tmp_path / "Dockerfile"
        f.write_text("EXPOSE 8080\n# second EXPOSE 8080\n")

        ps = PatchSuggestion(
            file="Dockerfile",
            description="fix",
            old_snippet="EXPOSE 8080",
            new_snippet="EXPOSE 8081",
        )
        apply_patch(ps, tmp_path)
        content = f.read_text()
        # Second occurrence untouched
        assert "EXPOSE 8080" in content  # the inline comment still has it
        lines = content.splitlines()
        assert lines[0] == "EXPOSE 8081"

    def test_append_preserves_existing_content(self, tmp_path: Path) -> None:
        original = "existing line\n"
        f = tmp_path / "config.toml"
        f.write_text(original)

        ps = PatchSuggestion(
            file="config.toml",
            description="add setting",
            old_snippet="",
            new_snippet="new_setting = true",
        )
        apply_patch(ps, tmp_path)
        content = f.read_text()
        assert "existing line" in content
        assert "new_setting" in content

    def test_empty_new_snippet_append_does_nothing(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("content")

        ps = PatchSuggestion(
            file="file.txt",
            description="no-op",
            old_snippet="",
            new_snippet="",  # empty → should not modify
        )
        result = apply_patch(ps, tmp_path)
        assert result is False
