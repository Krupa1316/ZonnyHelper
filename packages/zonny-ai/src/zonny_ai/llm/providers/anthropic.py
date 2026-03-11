"""Anthropic Claude LLM provider for zonny-helper."""
from __future__ import annotations

from typing import Iterator

from zonny_core.config.schema import AnthropicProviderConfig
from zonny_core.exceptions import LLMError, LLMProviderNotAvailable
from zonny_ai.llm.base import BaseLLMProvider
from zonny_ai.llm.cache import get_cached, set_cached


class AnthropicProvider(BaseLLMProvider):
    """Calls the Anthropic Messages API using the official `anthropic` SDK."""

    def __init__(self, config: AnthropicProviderConfig) -> None:
        self._config = config
        self._client = None  # lazy-initialized

    def _get_client(self):  # type: ignore[return]
        """Lazily initialize the Anthropic client."""
        if self._client is None:
            try:
                import anthropic  # noqa: PLC0415
            except ImportError as exc:
                raise LLMError(
                    "The 'anthropic' package is not installed. "
                    "Run: pip install 'zonny-helper[anthropic]'"
                ) from exc
            self._client = anthropic.Anthropic(api_key=self._config.api_key or None)
        return self._client

    def available(self) -> bool:
        return bool(self._config.api_key)

    def name(self) -> str:
        return f"Anthropic Claude ({self._config.model})"

    def generate(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        if not self.available():
            raise LLMProviderNotAvailable(
                "Anthropic API key is not set. "
                "Set ANTHROPIC_API_KEY or configure [llm.anthropic] in .zonny.toml"
            )
        cached = get_cached("anthropic", self._config.model, prompt, system)
        if cached is not None:
            return cached
        try:
            client = self._get_client()
            messages = [{"role": "user", "content": prompt}]
            kwargs: dict = {
                "model": self._config.model,
                "max_tokens": min(max_tokens, self._config.max_tokens),
                "messages": messages,
            }
            if system:
                kwargs["system"] = system
            response = client.messages.create(**kwargs)
            result = response.content[0].text.strip()
            set_cached("anthropic", self._config.model, prompt, system, result)
            return result
        except Exception as exc:
            raise LLMError(f"Anthropic API call failed: {exc}") from exc

    def stream(self, prompt: str, system: str = "", max_tokens: int = 2048) -> Iterator[str]:
        if not self.available():
            raise LLMProviderNotAvailable(
                "Anthropic API key is not set. "
                "Set ANTHROPIC_API_KEY or configure [llm.anthropic] in .zonny.toml"
            )
        try:
            client = self._get_client()
            messages = [{"role": "user", "content": prompt}]
            kwargs: dict = {
                "model": self._config.model,
                "max_tokens": min(max_tokens, self._config.max_tokens),
                "messages": messages,
            }
            if system:
                kwargs["system"] = system
            with client.messages.stream(**kwargs) as stream_ctx:
                for text in stream_ctx.text_stream:
                    yield text
        except Exception as exc:
            raise LLMError(f"Anthropic streaming call failed: {exc}") from exc
