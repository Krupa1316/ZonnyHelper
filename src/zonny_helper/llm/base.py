"""Abstract base class for all LLM providers in zonny-helper.

Any new provider must subclass BaseLLMProvider and implement:
  - generate()
  - available()
  - name()

The rest of the CLI is completely provider-agnostic; it only calls these methods.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator


class BaseLLMProvider(ABC):
    """Unified interface for LLM backends (Anthropic, OpenAI, Gemini, Ollama, …)."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
    ) -> str:
        """Generate a completion and return the full response text.

        Parameters
        ----------
        prompt:
            The user-facing prompt / message.
        system:
            Optional system / instruction message.
        max_tokens:
            Maximum tokens to generate.

        Returns
        -------
        str
            The model's response text (stripped).

        Raises
        ------
        LLMError
            On any network, auth, or quota failure.
        LLMProviderNotAvailable
            If the provider cannot be reached before the call.
        """

    def stream(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        """Stream response tokens.

        Default implementation yields the full generate() output as a single
        chunk. Providers that support native streaming should override this.
        """
        yield self.generate(prompt, system, max_tokens)

    @abstractmethod
    def available(self) -> bool:
        """Return True if this provider is reachable with the current config.

        For API providers this checks that an API key is set (and optionally
        makes a lightweight connectivity check).
        For Ollama this checks that the local server is responding.
        """

    @abstractmethod
    def name(self) -> str:
        """Return a human-readable provider name, e.g. 'Anthropic Claude'."""
