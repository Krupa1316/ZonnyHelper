"""Unit tests for LLM provider abstraction."""
from __future__ import annotations

import pytest

from tests.conftest import MockLLMProvider
from zonny_helper.config.schema import ZonnyConfig
from zonny_helper.exceptions import ZonnyConfigError
from zonny_helper.llm.base import BaseLLMProvider
from zonny_helper.llm.router import SUPPORTED_PROVIDERS, get_provider


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
        from zonny_helper.llm.providers.ollama import OllamaProvider  # noqa: PLC0415
        provider = get_provider(config, override="ollama")
        assert isinstance(provider, OllamaProvider)

    def test_anthropic_provider_instantiates(self) -> None:
        config = ZonnyConfig()
        from zonny_helper.llm.providers.anthropic import AnthropicProvider  # noqa: PLC0415
        provider = get_provider(config, override="anthropic")
        assert isinstance(provider, AnthropicProvider)
        assert provider.name().startswith("Anthropic")

    def test_openai_provider_instantiates(self) -> None:
        config = ZonnyConfig()
        from zonny_helper.llm.providers.openai import OpenAIProvider  # noqa: PLC0415
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
