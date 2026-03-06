"""Pydantic configuration schema for zonny-helper."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class GeneralConfig(BaseModel):
    output_format: Literal["rich", "json", "markdown"] = "rich"


# ── LLM provider configs ──────────────────────────────────────────────────────

class AnthropicProviderConfig(BaseModel):
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096


class OpenAIProviderConfig(BaseModel):
    api_key: str = ""
    model: str = "gpt-4o"
    max_tokens: int = 4096
    base_url: Optional[str] = None  # for Azure or custom endpoints


class GeminiProviderConfig(BaseModel):
    api_key: str = ""
    model: str = "gemini-2.0-flash"
    max_tokens: int = 4096


class OllamaProviderConfig(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "llama3"
    max_tokens: int = 4096


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    anthropic: AnthropicProviderConfig = Field(default_factory=AnthropicProviderConfig)
    openai: OpenAIProviderConfig = Field(default_factory=OpenAIProviderConfig)
    gemini: GeminiProviderConfig = Field(default_factory=GeminiProviderConfig)
    ollama: OllamaProviderConfig = Field(default_factory=OllamaProviderConfig)


# ── Git config ────────────────────────────────────────────────────────────────

class GitConfig(BaseModel):
    commit_style: Literal["conventional", "gitmoji", "plain"] = "conventional"
    auto_execute: bool = False
    default_base_branch: str = "main"


# ── Tree config ───────────────────────────────────────────────────────────────

class DBPatternsConfig(BaseModel):
    sqlalchemy: bool = True
    django_orm: bool = True
    prisma: bool = True
    mongoose: bool = True
    raw_sql: bool = True


class TreeConfig(BaseModel):
    languages: List[str] = Field(
        default_factory=lambda: ["python", "javascript", "typescript", "java", "go"]
    )
    ignore_patterns: List[str] = Field(
        default_factory=lambda: [
            "node_modules", ".venv", "__pycache__", "dist", "build",
            ".git", "*.min.js", "*.min.css",
        ]
    )
    max_file_size_kb: int = 500
    enrich_by_default: bool = True
    db_patterns: DBPatternsConfig = Field(default_factory=DBPatternsConfig)


# ── Root config ───────────────────────────────────────────────────────────────

class ZonnyConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    tree: TreeConfig = Field(default_factory=TreeConfig)
