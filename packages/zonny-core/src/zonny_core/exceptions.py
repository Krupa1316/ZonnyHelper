"""Typed exception hierarchy for zonny-helper.

All user-facing errors should be one of these types so that the CLI layer
can catch them and render a consistent Rich error message.
"""


class ZonnyError(Exception):
    """Base exception for all zonny-helper errors."""


class ZonnyConfigError(ZonnyError):
    """Raised when configuration is invalid or missing required values."""


class GitError(ZonnyError):
    """Raised when a git subprocess command fails."""


class LLMError(ZonnyError):
    """Raised when an LLM provider call fails (network, auth, quota, etc.)."""


class LLMProviderNotAvailable(LLMError):
    """Raised when the configured provider cannot be reached."""


class ParseError(ZonnyError):
    """Raised when AST or diff parsing fails unexpectedly."""


class TreeError(ZonnyError):
    """Raised during codebase tree building or querying."""
