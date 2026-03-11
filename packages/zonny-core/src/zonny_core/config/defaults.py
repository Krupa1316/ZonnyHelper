"""Default configuration values for zonny-helper."""
from __future__ import annotations

DEFAULTS: dict = {
    "general": {
        "output_format": "rich",
    },
    "llm": {
        "provider": "anthropic",
        "anthropic": {
            "api_key": "",
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
        },
        "openai": {
            "api_key": "",
            "model": "gpt-4o",
            "max_tokens": 4096,
            "base_url": "",
        },
        "gemini": {
            "api_key": "",
            "model": "gemini-2.0-flash",
            "max_tokens": 4096,
        },
        "ollama": {
            "host": "http://localhost:11434",
            "model": "llama3",
            "max_tokens": 4096,
        },
    },
    "git": {
        "commit_style": "conventional",
        "auto_execute": False,
        "default_base_branch": "main",
    },
    "tree": {
        "languages": ["python", "javascript", "typescript", "java", "go"],
        "ignore_patterns": [
            "node_modules", ".venv", "__pycache__", "dist", "build",
            ".git", "*.min.js", "*.min.css",
        ],
        "max_file_size_kb": 500,
        "enrich_by_default": True,
        "db_patterns": {
            "sqlalchemy": True,
            "django_orm": True,
            "prisma": True,
            "mongoose": True,
            "raw_sql": True,
        },
    },
}
