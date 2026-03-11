"""Pydantic configuration schema for zonny-helper."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class GeneralConfig(BaseModel):
    output_format: Literal["rich", "json", "markdown"] = "rich"


# â”€â”€ LLM provider configs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Git config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class GitConfig(BaseModel):
    commit_style: Literal["conventional", "gitmoji", "plain"] = "conventional"
    auto_execute: bool = False
    default_base_branch: str = "main"


# â”€â”€ Tree config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# ── Deploy / networking config ────────────────────────────────────────────────


class CloudflareTunnelConfig(BaseModel):
    """Cloudflare Tunnel integration.

    One-time setup::

        zonny config set deploy.networking.cloudflare_tunnel.api_token <token>

    Get a token at https://dash.cloudflare.com/profile/api-tokens with
    permissions: Zone:DNS:Edit + Account:Cloudflare Tunnel:Edit.

    After that a single ``zonny deploy cloudflare`` call will:
      1. Detect the local tunnel and extract Account/Tunnel IDs from the
         Windows service token (no manual credential setup required).
      2. Auto-pick a hostname from existing tunnel routes (e.g. zonny.me).
      3. Call the Cloudflare API to add the ingress rule to the tunnel.
      4. Call the Cloudflare API to create/update the DNS CNAME record.
      5. Start cloudflared with synthesised credentials.
      6. Verify the public URL is live and print it.
    """

    enabled: bool = False
    tunnel_id: str = ""
    token: str = ""         # CLOUDFLARE_TUNNEL_TOKEN env var or inline
    hostname: str = ""      # e.g. "api.example.com"
    local_port: int = 8000  # must match the app's listen port
    api_token: str = ""     # Cloudflare API token for DNS + ingress management


class NginxConfig(BaseModel):
    """Nginx reverse-proxy configuration.

    When ``enabled=True``, zonny generates a minimal ``nginx.conf`` alongside
    the other config files so Nginx can front the application.
    """

    enabled: bool = False
    listen_port: int = 80
    server_name: str = "_"       # catch-all by default
    proxy_pass_port: int = 8000  # must match the app's listen port
    ssl: bool = False
    ssl_cert: str = ""           # path to PEM cert file
    ssl_key: str = ""            # path to PEM key file
    extra_directives: List[str] = Field(
        default_factory=list,
        description="Raw nginx config lines appended inside the server{} block.",
    )


class NetworkingConfig(BaseModel):
    """Bundled networking integrations.

    Configure reverse proxies and tunnel services here. New providers can
    be added by placing their config under the ``extras`` dict in
    :class:`DeployConfig`.
    """

    cloudflare_tunnel: CloudflareTunnelConfig = Field(default_factory=CloudflareTunnelConfig)
    nginx: NginxConfig = Field(default_factory=NginxConfig)


class DeployConfig(BaseModel):
    """Controls the self-healing retry loop and all deployment integrations.

    This is the central place for users to configure deployment behaviour,
    networking integrations, and arbitrary custom settings.

    Example ``config.toml`` section::

        [deploy]
        max_attempts = 3
        health_check_path = "/healthz"
        auto_rollback = true

        [deploy.networking.cloudflare_tunnel]
        enabled = true
        token = "my-tunnel-token"
        hostname = "api.example.com"

        [deploy.networking.nginx]
        enabled = true
        listen_port = 80
        proxy_pass_port = 8000

        [deploy.extras]
        my_custom_key = "anything"
        another_setting = 42
    """

    max_attempts: int = 3
    health_check_path: str = "/health"
    health_check_timeout_s: int = 60
    health_check_retries: int = 5
    auto_rollback: bool = True
    networking: NetworkingConfig = Field(default_factory=NetworkingConfig)
    extras: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary key-value store for custom integrations and settings. "
            "Anything placed here is passed through to generators and runners "
            "as-is, making it easy to add support for new tools without "
            "changing the schema."
        ),
    )


# ── Root config ───────────────────────────────────────────────────────────────

class ZonnyConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    tree: TreeConfig = Field(default_factory=TreeConfig)
    deploy: DeployConfig = Field(default_factory=DeployConfig)
