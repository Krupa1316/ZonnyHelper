"""Google Gemini LLM provider for zonny-helper."""
from __future__ import annotations

from zonny_core.config.schema import GeminiProviderConfig
from zonny_core.exceptions import LLMError, LLMProviderNotAvailable
from zonny_ai.llm.base import BaseLLMProvider
from zonny_ai.llm.cache import get_cached, set_cached


class GeminiProvider(BaseLLMProvider):
    """Calls the Google Gemini API using the `google-genai` SDK."""

    def __init__(self, config: GeminiProviderConfig) -> None:
        self._config = config
        self._client = None  # lazy-initialized

    def _get_client(self):  # type: ignore[return]
        if self._client is None:
            try:
                from google import genai  # noqa: PLC0415
            except ImportError as exc:
                raise LLMError(
                    "The 'google-genai' package is not installed. "
                    "Run: pip install 'zonny-helper[gemini]'"
                ) from exc
            self._client = genai.Client(api_key=self._config.api_key or None)
        return self._client

    def available(self) -> bool:
        return bool(self._config.api_key)

    def name(self) -> str:
        return f"Google Gemini ({self._config.model})"

    def generate(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        if not self.available():
            raise LLMProviderNotAvailable(
                "Google API key is not set. "
                "Set GOOGLE_API_KEY or configure [llm.gemini] in .zonny.toml"
            )
        cached = get_cached("gemini", self._config.model, prompt, system)
        if cached is not None:
            return cached
        try:
            from google.genai import types  # noqa: PLC0415

            client = self._get_client()
            config = types.GenerateContentConfig(
                max_output_tokens=min(max_tokens, self._config.max_tokens),
                system_instruction=system or None,
            )
            response = client.models.generate_content(
                model=self._config.model,
                contents=prompt,
                config=config,
            )
            result = (response.text or "").strip()
            set_cached("gemini", self._config.model, prompt, system, result)
            return result
        except Exception as exc:
            raise LLMError(f"Gemini API call failed: {exc}") from exc
