"""OpenAI GPT LLM provider for zonny-helper.

Supports any OpenAI-compatible endpoint via the `base_url` config option,
including Azure OpenAI, Together AI, and Groq.
"""
from __future__ import annotations

from typing import Iterator

from zonny_helper.config.schema import OpenAIProviderConfig
from zonny_helper.exceptions import LLMError, LLMProviderNotAvailable
from zonny_helper.llm.base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """Calls the OpenAI Chat Completions API."""

    def __init__(self, config: OpenAIProviderConfig) -> None:
        self._config = config
        self._client = None  # lazy-initialized

    def _get_client(self):  # type: ignore[return]
        if self._client is None:
            try:
                import openai  # noqa: PLC0415
            except ImportError as exc:
                raise LLMError(
                    "The 'openai' package is not installed. "
                    "Run: pip install 'zonny-helper[openai]'"
                ) from exc
            kwargs: dict = {"api_key": self._config.api_key or None}
            if self._config.base_url:
                kwargs["base_url"] = self._config.base_url
            self._client = openai.OpenAI(**kwargs)
        return self._client

    def available(self) -> bool:
        return bool(self._config.api_key)

    def name(self) -> str:
        return f"OpenAI ({self._config.model})"

    def generate(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        if not self.available():
            raise LLMProviderNotAvailable(
                "OpenAI API key is not set. "
                "Set OPENAI_API_KEY or configure [llm.openai] in .zonny.toml"
            )
        try:
            client = self._get_client()
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(
                model=self._config.model,
                max_tokens=min(max_tokens, self._config.max_tokens),
                messages=messages,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            raise LLMError(f"OpenAI API call failed: {exc}") from exc

    def stream(self, prompt: str, system: str = "", max_tokens: int = 2048) -> Iterator[str]:
        if not self.available():
            raise LLMProviderNotAvailable(
                "OpenAI API key is not set. "
                "Set OPENAI_API_KEY or configure [llm.openai] in .zonny.toml"
            )
        try:
            client = self._get_client()
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            with client.chat.completions.stream(
                model=self._config.model,
                max_tokens=min(max_tokens, self._config.max_tokens),
                messages=messages,
            ) as stream_ctx:
                for chunk in stream_ctx:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
        except Exception as exc:
            raise LLMError(f"OpenAI streaming call failed: {exc}") from exc
