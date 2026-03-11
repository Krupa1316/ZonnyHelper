"""LLM provider factory (router) for zonny-helper.

Call `get_provider(config)` to get the correct BaseLLMProvider instance
based on the active configuration and optional CLI override.
"""
from __future__ import annotations

from zonny_core.config.schema import ZonnyConfig
from zonny_core.exceptions import ZonnyConfigError
from zonny_ai.llm.base import BaseLLMProvider

SUPPORTED_PROVIDERS = ("anthropic", "openai", "gemini", "ollama")


def get_provider(
    config: ZonnyConfig,
    override: str | None = None,
) -> BaseLLMProvider:
    """Instantiate and return the configured LLM provider.

    Parameters
    ----------
    config:
        The loaded ZonnyConfig.
    override:
        Optional provider name that overrides the config value,
        typically passed from a ``--provider`` CLI flag.

    Returns
    -------
    BaseLLMProvider
        A ready-to-use provider instance.

    Raises
    ------
    ZonnyConfigError
        If the provider name is not recognised.
    """
    provider_name = (override or config.llm.provider).lower().strip()

    match provider_name:
        case "anthropic":
            from zonny_ai.llm.providers.anthropic import AnthropicProvider  # noqa: PLC0415
            return AnthropicProvider(config.llm.anthropic)

        case "openai":
            from zonny_ai.llm.providers.openai import OpenAIProvider  # noqa: PLC0415
            return OpenAIProvider(config.llm.openai)

        case "gemini":
            from zonny_ai.llm.providers.gemini import GeminiProvider  # noqa: PLC0415
            return GeminiProvider(config.llm.gemini)

        case "ollama":
            from zonny_ai.llm.providers.ollama import OllamaProvider  # noqa: PLC0415
            return OllamaProvider(config.llm.ollama)

        case _:
            supported = ", ".join(SUPPORTED_PROVIDERS)
            raise ZonnyConfigError(
                f"Unknown LLM provider '{provider_name}'. "
                f"Supported providers: {supported}"
            )
