"""Ollama local LLM provider for zonny-helper.

Communicates with a locally-running Ollama server via its REST API.
No API key is needed â€” just have `ollama serve` running and the model pulled.
"""
from __future__ import annotations

from typing import Iterator

import httpx

from zonny_core.config.schema import OllamaProviderConfig
from zonny_core.exceptions import LLMError, LLMProviderNotAvailable
from zonny_ai.llm.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """Calls a locally-running Ollama server via its REST API."""

    def __init__(self, config: OllamaProviderConfig) -> None:
        self._config = config

    def available(self) -> bool:
        """Return True if the Ollama server is reachable at the configured host."""
        try:
            r = httpx.get(f"{self._config.host}/api/tags", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def name(self) -> str:
        return f"Ollama ({self._config.model} @ {self._config.host})"

    def _check_model_exists(self) -> None:
        """Raise LLMError if the configured model hasn't been pulled."""
        try:
            r = httpx.get(f"{self._config.host}/api/tags", timeout=5.0)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            # Ollama often appends :latest, so check by prefix
            if not any(m.startswith(self._config.model.split(":")[0]) for m in models):
                raise LLMError(
                    f"Model '{self._config.model}' not found in Ollama. "
                    f"Run: ollama pull {self._config.model}"
                )
        except httpx.RequestError as exc:
            raise LLMProviderNotAvailable(
                f"Cannot connect to Ollama at {self._config.host}. "
                "Is `ollama serve` running?"
            ) from exc

    def generate(self, prompt: str, system: str = "", max_tokens: int = 2048) -> str:
        if not self.available():
            raise LLMProviderNotAvailable(
                f"Cannot connect to Ollama at {self._config.host}. "
                "Is `ollama serve` running?"
            )
        self._check_model_exists()
        payload: dict = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": min(max_tokens, self._config.max_tokens)},
        }
        if system:
            payload["system"] = system
        try:
            r = httpx.post(
                f"{self._config.host}/api/generate",
                json=payload,
                timeout=180.0,
            )
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except httpx.RequestError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"Ollama returned HTTP {exc.response.status_code}") from exc

    def stream(self, prompt: str, system: str = "", max_tokens: int = 2048) -> Iterator[str]:
        """Stream tokens from Ollama's generate endpoint."""
        if not self.available():
            raise LLMProviderNotAvailable(
                f"Cannot connect to Ollama at {self._config.host}. "
                "Is `ollama serve` running?"
            )
        self._check_model_exists()
        payload: dict = {
            "model": self._config.model,
            "prompt": prompt,
            "stream": True,
            "options": {"num_predict": min(max_tokens, self._config.max_tokens)},
        }
        if system:
            payload["system"] = system
        try:
            import json  # noqa: PLC0415
            with httpx.stream("POST", f"{self._config.host}/api/generate", json=payload, timeout=180.0) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        data = json.loads(line)
                        token = data.get("response", "")
                        if token:
                            yield token
                        if data.get("done"):
                            break
        except httpx.RequestError as exc:
            raise LLMError(f"Ollama streaming request failed: {exc}") from exc
