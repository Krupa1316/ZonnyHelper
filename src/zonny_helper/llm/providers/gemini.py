"""Google Gemini LLM provider for zonny-helper."""
from __future__ import annotations

from zonny_helper.config.schema import GeminiProviderConfig
from zonny_helper.exceptions import LLMError, LLMProviderNotAvailable
from zonny_helper.llm.base import BaseLLMProvider


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
            return (response.text or "").strip()
        except Exception as exc:
            raise LLMError(f"Gemini API call failed: {exc}") from exc
