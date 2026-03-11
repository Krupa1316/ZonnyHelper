"""Unit tests for zonny config commands."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from zonny_core.config.commands import app, _GLOBAL_CONFIG_FILE, _GLOBAL_CONFIG_DIR

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch):
    """Redirect config file to a tmp location for every test."""
    fake_dir  = tmp_path / ".zonny_test"
    fake_file = fake_dir / "config.toml"
    monkeypatch.setattr("zonny_core.config.commands._GLOBAL_CONFIG_DIR",  fake_dir)
    monkeypatch.setattr("zonny_core.config.commands._GLOBAL_CONFIG_FILE", fake_file)
    yield fake_file


class TestSetKey:
    def test_set_anthropic_key_writes_file(self, _isolated_config: Path) -> None:
        result = runner.invoke(app, ["set-key", "anthropic", "sk-ant-test-123"])
        assert result.exit_code == 0
        assert _isolated_config.exists()
        content = _isolated_config.read_text()
        assert "sk-ant-test-123" in content

    def test_set_openai_key(self, _isolated_config: Path) -> None:
        result = runner.invoke(app, ["set-key", "openai", "sk-openai-xyz"])
        assert result.exit_code == 0
        assert "sk-openai-xyz" in _isolated_config.read_text()

    def test_unknown_provider_exits_with_error(self, _isolated_config: Path) -> None:
        result = runner.invoke(app, ["set-key", "cohere", "key123"])
        assert result.exit_code == 1

    def test_second_set_overwrites_first(self, _isolated_config: Path) -> None:
        runner.invoke(app, ["set-key", "anthropic", "old-key"])
        runner.invoke(app, ["set-key", "anthropic", "new-key"])
        assert "new-key" in _isolated_config.read_text()
        assert "old-key" not in _isolated_config.read_text()


class TestUnsetKey:
    def test_unset_removes_key(self, _isolated_config: Path) -> None:
        runner.invoke(app, ["set-key", "anthropic", "sk-ant-test"])
        runner.invoke(app, ["unset-key", "anthropic"])
        content = _isolated_config.read_text()
        # Key should be empty string, not the actual value
        assert "sk-ant-test" not in content

    def test_unset_nonexistent_key_warns(self, _isolated_config: Path) -> None:
        result = runner.invoke(app, ["unset-key", "openai"])
        assert result.exit_code == 0  # should exit cleanly with a warning


class TestListConfig:
    def test_list_shows_all_providers(self, _isolated_config: Path) -> None:
        runner.invoke(app, ["set-key", "anthropic", "sk-ant-test"])
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "anthropic" in result.output

    def test_list_masks_key(self, _isolated_config: Path) -> None:
        runner.invoke(app, ["set-key", "anthropic", "sk-ant-api03-supersecret"])
        result = runner.invoke(app, ["list"])
        # Full key should NOT appear in output
        assert "supersecret" not in result.output
        # Masked prefix should appear (first 7 chars of key)
        assert "sk-ant-" in result.output
        assert "***" in result.output

    def test_list_shows_not_set_for_empty_keys(self, _isolated_config: Path) -> None:
        result = runner.invoke(app, ["list"])
        assert "not set" in result.output


class TestSetAndGet:
    def test_set_default_deploy_target(self, _isolated_config: Path) -> None:
        result = runner.invoke(app, ["set", "defaults.deploy_target", "kubernetes"])
        assert result.exit_code == 0
        content = _isolated_config.read_text()
        assert "kubernetes" in content

    def test_get_default_value(self, _isolated_config: Path) -> None:
        runner.invoke(app, ["set", "defaults.deploy_target", "ecs-fargate"])
        result = runner.invoke(app, ["get", "defaults.deploy_target"])
        assert result.exit_code == 0
        assert "ecs-fargate" in result.output

    def test_set_requires_dot_notation(self, _isolated_config: Path) -> None:
        result = runner.invoke(app, ["set", "nodeploykey", "value"])
        assert result.exit_code == 1

    def test_get_missing_key_exits_with_error(self, _isolated_config: Path) -> None:
        result = runner.invoke(app, ["get", "defaults.nonexistent_key"])
        assert result.exit_code == 1

    def test_get_key_masks_api_key(self, _isolated_config: Path) -> None:
        runner.invoke(app, ["set-key", "anthropic", "sk-ant-api03-secret"])
        result = runner.invoke(app, ["get", "keys.anthropic"])
        assert result.exit_code == 0
        assert "sk-ant-" in result.output
        assert "***" in result.output
        assert "secret" not in result.output
