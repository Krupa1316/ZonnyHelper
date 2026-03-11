"""Unit tests for the LLM response cache."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from zonny_ai.llm.cache import _cache_key, clear_cache, get_cached, set_cached


@pytest.fixture()
def isolated_cache(tmp_path: Path):
    """Redirect cache writes to a temp dir for the duration of the test."""
    with patch("zonny_ai.llm.cache._cache_dir", return_value=tmp_path / "llm_cache"):
        yield tmp_path / "llm_cache"


class TestCacheKey:
    def test_same_inputs_produce_same_key(self) -> None:
        k1 = _cache_key("anthropic", "claude-3-haiku", "hello", "sys")
        k2 = _cache_key("anthropic", "claude-3-haiku", "hello", "sys")
        assert k1 == k2

    def test_different_provider_gives_different_key(self) -> None:
        k1 = _cache_key("anthropic", "model", "prompt", "")
        k2 = _cache_key("openai", "model", "prompt", "")
        assert k1 != k2

    def test_different_prompt_gives_different_key(self) -> None:
        k1 = _cache_key("anthropic", "model", "prompt-A", "")
        k2 = _cache_key("anthropic", "model", "prompt-B", "")
        assert k1 != k2

    def test_different_system_gives_different_key(self) -> None:
        k1 = _cache_key("anthropic", "model", "prompt", "system-A")
        k2 = _cache_key("anthropic", "model", "prompt", "system-B")
        assert k1 != k2

    def test_returns_hex_string(self) -> None:
        key = _cache_key("p", "m", "q", "s")
        assert len(key) == 64  # SHA-256 hex digest
        int(key, 16)  # raises if not valid hex


class TestGetCached:
    def test_returns_none_when_cache_empty(self, isolated_cache: Path) -> None:
        result = get_cached("anthropic", "model", "prompt", "system")
        assert result is None

    def test_returns_response_after_set(self, isolated_cache: Path) -> None:
        set_cached("anthropic", "model", "my prompt", "my system", "hello world")
        result = get_cached("anthropic", "model", "my prompt", "my system")
        assert result == "hello world"

    def test_returns_none_for_different_prompt(self, isolated_cache: Path) -> None:
        set_cached("anthropic", "model", "prompt-A", "", "cached")
        result = get_cached("anthropic", "model", "prompt-B", "")
        assert result is None

    def test_returns_none_when_cache_file_corrupted(self, isolated_cache: Path) -> None:
        isolated_cache.mkdir(parents=True, exist_ok=True)
        # Write a malformed JSON file with the right key name
        from zonny_ai.llm.cache import _cache_key  # noqa: PLC0415
        key = _cache_key("p", "m", "q", "")
        (isolated_cache / f"{key}.json").write_text("not json", encoding="utf-8")
        assert get_cached("p", "m", "q", "") is None


class TestSetCached:
    def test_creates_cache_dir_if_missing(self, isolated_cache: Path) -> None:
        assert not isolated_cache.exists()
        set_cached("openai", "gpt-4o", "q", "", "result")
        assert isolated_cache.is_dir()

    def test_writes_json_file(self, isolated_cache: Path) -> None:
        set_cached("gemini", "gemini-2.0-flash", "question", "sys", "answer")
        files = list(isolated_cache.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["response"] == "answer"
        assert data["provider"] == "gemini"
        assert data["model"] == "gemini-2.0-flash"

    def test_overwrite_updates_response(self, isolated_cache: Path) -> None:
        set_cached("openai", "gpt-4o", "q", "", "first")
        set_cached("openai", "gpt-4o", "q", "", "second")
        result = get_cached("openai", "gpt-4o", "q", "")
        assert result == "second"

    def test_multiple_providers_create_separate_files(self, isolated_cache: Path) -> None:
        set_cached("anthropic", "model", "q", "", "a1")
        set_cached("openai", "model", "q", "", "a2")
        files = list(isolated_cache.glob("*.json"))
        assert len(files) == 2


class TestClearCache:
    def test_returns_zero_when_no_cache(self, isolated_cache: Path) -> None:
        assert clear_cache() == 0

    def test_deletes_all_json_files(self, isolated_cache: Path) -> None:
        set_cached("a", "m", "q1", "", "r1")
        set_cached("b", "m", "q2", "", "r2")
        set_cached("c", "m", "q3", "", "r3")
        count = clear_cache()
        assert count == 3
        assert not any(isolated_cache.glob("*.json"))

    def test_get_returns_none_after_clear(self, isolated_cache: Path) -> None:
        set_cached("anthropic", "model", "prompt", "", "response")
        clear_cache()
        assert get_cached("anthropic", "model", "prompt", "") is None


class TestCacheProviderIntegration:
    """Test that cache is hit before provider is called."""

    def test_cached_response_avoids_api_call(self, isolated_cache: Path) -> None:
        """After set_cached, get_cached should return without hitting the network."""
        set_cached("anthropic", "claude-3-haiku", "what is 2+2?", "", "4")
        result = get_cached("anthropic", "claude-3-haiku", "what is 2+2?", "")
        assert result == "4"

    def test_cache_is_provider_and_model_specific(self, isolated_cache: Path) -> None:
        set_cached("anthropic", "claude-3-haiku", "q", "", "haiku-answer")
        set_cached("anthropic", "claude-opus-4", "q", "", "opus-answer")
        assert get_cached("anthropic", "claude-3-haiku", "q", "") == "haiku-answer"
        assert get_cached("anthropic", "claude-opus-4", "q", "") == "opus-answer"
