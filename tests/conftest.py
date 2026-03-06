"""Pytest shared fixtures for zonny-helper tests.

Provides:
  - `mock_llm`: a MockLLMProvider that returns configurable responses
  - `tmp_git_repo`: a temporary directory initialized as a git repository
  - `sample_config`: a ZonnyConfig with safe test defaults
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterator

import pytest

from zonny_helper.config.schema import ZonnyConfig
from zonny_helper.llm.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """A fake LLM provider for tests.

    Configure responses via the `responses` list; each call pops the next response.
    If `responses` is exhausted, returns `default_response`.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        default_response: str = "mock response",
    ) -> None:
        self.responses: list[str] = list(responses or [])
        self.default_response = default_response
        self.calls: list[dict] = []  # records all calls for assertion

    def generate(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens})
        if self.responses:
            return self.responses.pop(0)
        return self.default_response

    def available(self) -> bool:
        return True

    def name(self) -> str:
        return "Mock LLM"


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    """Return a fresh MockLLMProvider."""
    return MockLLMProvider()


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary git repository and yield its path."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@zonny.dev"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    yield tmp_path


@pytest.fixture
def sample_config() -> ZonnyConfig:
    """Return a ZonnyConfig with safe test defaults (no real API keys)."""
    return ZonnyConfig()
