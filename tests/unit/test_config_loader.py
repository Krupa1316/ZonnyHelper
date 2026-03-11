"""Unit tests for the configuration loader."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from zonny_core.config.loader import _deep_merge, _find_project_config, load_config
from zonny_core.config.schema import ZonnyConfig


class TestDeepMerge:
    def test_simple_merge(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_nested_merge(self) -> None:
        base = {"llm": {"provider": "anthropic", "anthropic": {"api_key": "", "model": "x"}}}
        override = {"llm": {"provider": "openai", "anthropic": {"api_key": "sk-test"}}}
        result = _deep_merge(base, override)
        assert result["llm"]["provider"] == "openai"
        assert result["llm"]["anthropic"]["api_key"] == "sk-test"
        assert result["llm"]["anthropic"]["model"] == "x"  # preserved from base

    def test_does_not_mutate_base(self) -> None:
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        _deep_merge(base, override)
        assert "c" not in base["a"]


class TestLoadConfig:
    def test_returns_zonny_config(self) -> None:
        config = load_config()
        assert isinstance(config, ZonnyConfig)

    def test_default_provider_is_anthropic(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Isolate from any real config file so pure defaults apply
        monkeypatch.setattr(
            "zonny_core.config.loader._global_config_path",
            lambda: tmp_path / "no-such-config.toml",
        )
        config = load_config()
        assert config.llm.provider == "anthropic"

    def test_cli_override_wins(self) -> None:
        config = load_config({"llm": {"provider": "ollama"}})
        assert config.llm.provider == "ollama"

    def test_env_var_sets_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
        config = load_config()
        assert config.llm.anthropic.api_key == "sk-from-env"

    def test_openai_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        config = load_config()
        assert config.llm.openai.api_key == "sk-openai-test"

    def test_project_config_loaded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        toml_content = '[llm]\nprovider = "gemini"\n'
        (tmp_path / ".zonny.toml").write_text(toml_content)
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.llm.provider == "gemini"

    def test_cli_override_beats_project_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / ".zonny.toml").write_text('[llm]\nprovider = "gemini"\n')
        monkeypatch.chdir(tmp_path)
        config = load_config({"llm": {"provider": "openai"}})
        assert config.llm.provider == "openai"


class TestFindProjectConfig:
    def test_finds_in_current_dir(self, tmp_path: Path) -> None:
        cfg = tmp_path / ".zonny.toml"
        cfg.write_text("")
        result = _find_project_config(start=tmp_path)
        assert result == cfg

    def test_finds_in_parent(self, tmp_path: Path) -> None:
        cfg = tmp_path / ".zonny.toml"
        cfg.write_text("")
        subdir = tmp_path / "a" / "b"
        subdir.mkdir(parents=True)
        result = _find_project_config(start=subdir)
        assert result == cfg

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        result = _find_project_config(start=tmp_path)
        assert result is None
