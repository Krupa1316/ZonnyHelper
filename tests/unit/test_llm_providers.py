"""Unit tests for LLM provider abstraction."""
from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider
from zonny_core.config.schema import ZonnyConfig
from zonny_core.exceptions import ZonnyConfigError
from zonny_ai.llm.base import BaseLLMProvider
from zonny_ai.llm.router import SUPPORTED_PROVIDERS, get_provider


class TestMockProvider:
    def test_implements_base(self) -> None:
        provider = MockLLMProvider()
        assert isinstance(provider, BaseLLMProvider)

    def test_generate_returns_default(self) -> None:
        provider = MockLLMProvider(default_response="hello!")
        assert provider.generate("test") == "hello!"

    def test_generate_pops_responses(self) -> None:
        provider = MockLLMProvider(responses=["first", "second"])
        assert provider.generate("q1") == "first"
        assert provider.generate("q2") == "second"
        assert provider.generate("q3") == "mock response"  # default

    def test_calls_are_recorded(self) -> None:
        provider = MockLLMProvider()
        provider.generate("my prompt", system="my system")
        assert len(provider.calls) == 1
        assert provider.calls[0]["prompt"] == "my prompt"
        assert provider.calls[0]["system"] == "my system"

    def test_available_always_true(self) -> None:
        assert MockLLMProvider().available() is True

    def test_stream_yields_full_response(self) -> None:
        provider = MockLLMProvider(responses=["streamed!"])
        chunks = list(provider.stream("q"))
        assert "".join(chunks) == "streamed!"


class TestRouter:
    def test_all_supported_providers_listed(self) -> None:
        assert "anthropic" in SUPPORTED_PROVIDERS
        assert "openai"    in SUPPORTED_PROVIDERS
        assert "gemini"    in SUPPORTED_PROVIDERS
        assert "ollama"    in SUPPORTED_PROVIDERS

    def test_unknown_provider_raises_config_error(self) -> None:
        config = ZonnyConfig()
        with pytest.raises(ZonnyConfigError, match="Unknown LLM provider"):
            get_provider(config, override="fakeai")

    def test_override_takes_precedence(self) -> None:
        """get_provider with override='ollama' should return OllamaProvider even if config says anthropic."""
        config = ZonnyConfig()  # default provider is anthropic
        from zonny_ai.llm.providers.ollama import OllamaProvider  # noqa: PLC0415
        provider = get_provider(config, override="ollama")
        assert isinstance(provider, OllamaProvider)

    def test_anthropic_provider_instantiates(self) -> None:
        config = ZonnyConfig()
        from zonny_ai.llm.providers.anthropic import AnthropicProvider  # noqa: PLC0415
        provider = get_provider(config, override="anthropic")
        assert isinstance(provider, AnthropicProvider)
        assert provider.name().startswith("Anthropic")

    def test_openai_provider_instantiates(self) -> None:
        config = ZonnyConfig()
        from zonny_ai.llm.providers.openai import OpenAIProvider  # noqa: PLC0415
        provider = get_provider(config, override="openai")
        assert isinstance(provider, OpenAIProvider)
        assert provider.name().startswith("OpenAI")

    def test_ollama_not_available_without_server(self) -> None:
        """OllamaProvider.available() should return False if nothing is running on port 11434."""
        config = ZonnyConfig()
        # Use a non-existent host to guarantee unavailability
        config.llm.ollama.host = "http://127.0.0.1:19999"
        provider = get_provider(config, override="ollama")
        assert provider.available() is False

    def test_anthropic_not_available_without_key(self) -> None:
        config = ZonnyConfig()
        config.llm.anthropic.api_key = ""
        provider = get_provider(config, override="anthropic")
        assert provider.available() is False

    def test_openai_not_available_without_key(self) -> None:
        config = ZonnyConfig()
        config.llm.openai.api_key = ""
        provider = get_provider(config, override="openai")
        assert provider.available() is False
    def test_gemini_provider_instantiates(self) -> None:
        config = ZonnyConfig()
        from zonny_ai.llm.providers.gemini import GeminiProvider  # noqa: PLC0415
        provider = get_provider(config, override="gemini")
        assert isinstance(provider, GeminiProvider)
        assert provider.name().startswith("Google Gemini")

    def test_gemini_not_available_without_key(self) -> None:
        config = ZonnyConfig()
        config.llm.gemini.api_key = ""
        provider = get_provider(config, override="gemini")
        assert provider.available() is False

    def test_gemini_available_with_key(self) -> None:
        config = ZonnyConfig()
        config.llm.gemini.api_key = "fake-test-key"
        provider = get_provider(config, override="gemini")
        assert provider.available() is True


class TestProviderCacheIntegration:
    """Verify providers read from / write to cache around API calls."""

    def test_anthropic_uses_cache_on_hit(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from pathlib import Path  # noqa: PLC0415
        from unittest.mock import patch  # noqa: PLC0415

        cache_dir = tmp_path / "llm_cache"
        with patch("zonny_ai.llm.cache._cache_dir", return_value=cache_dir):
            from zonny_ai.llm.cache import set_cached  # noqa: PLC0415
            from zonny_ai.llm.providers.anthropic import AnthropicProvider  # noqa: PLC0415
            from zonny_core.config.schema import AnthropicProviderConfig  # noqa: PLC0415

            cfg = AnthropicProviderConfig(api_key="fake", model="claude-3-haiku-20240307")
            provider = AnthropicProvider(cfg)

            # Seed the cache
            set_cached("anthropic", "claude-3-haiku-20240307", "2+2?", "", "4")

            # generate() should return cached value without hitting the API
            result = provider.generate("2+2?", system="")
            assert result == "4"

    def test_gemini_uses_cache_on_hit(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import patch  # noqa: PLC0415

        cache_dir = tmp_path / "llm_cache"
        with patch("zonny_ai.llm.cache._cache_dir", return_value=cache_dir):
            from zonny_ai.llm.cache import set_cached  # noqa: PLC0415
            from zonny_ai.llm.providers.gemini import GeminiProvider  # noqa: PLC0415
            from zonny_core.config.schema import GeminiProviderConfig  # noqa: PLC0415

            cfg = GeminiProviderConfig(api_key="fake", model="gemini-2.0-flash")
            provider = GeminiProvider(cfg)

            set_cached("gemini", "gemini-2.0-flash", "capital of France?", "", "Paris")
            result = provider.generate("capital of France?", system="")
            assert result == "Paris"

    def test_openai_uses_cache_on_hit(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import patch  # noqa: PLC0415

        cache_dir = tmp_path / "llm_cache"
        with patch("zonny_ai.llm.cache._cache_dir", return_value=cache_dir):
            from zonny_ai.llm.cache import set_cached  # noqa: PLC0415
            from zonny_ai.llm.providers.openai import OpenAIProvider  # noqa: PLC0415
            from zonny_core.config.schema import OpenAIProviderConfig  # noqa: PLC0415

            cfg = OpenAIProviderConfig(api_key="fake", model="gpt-4o-mini")
            provider = OpenAIProvider(cfg)

            set_cached("openai", "gpt-4o-mini", "hello?", "", "hi there")
            result = provider.generate("hello?", system="")
            assert result == "hi there"