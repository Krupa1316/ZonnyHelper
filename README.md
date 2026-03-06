# Zonny Helper

> AI-powered CLI for git automation and codebase intelligence

```
pip install zonny-helper
```

[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)

---

## What is Zonny Helper?

**Zonny Helper** is a developer intelligence CLI that brings AI directly into your terminal.  
It combines two capabilities under `zonny`:

| Module | Commands | Purpose |
|--------|----------|---------|
| **Git Automation** | `zonny git commit/pr/changelog/whybroke` | Turn diffs into commits, PRs, and changelogs |
| **Codebase Intelligence** | `zonny tree build/query/diff/export` | Map every function, class, and DB call into a queryable entity graph |

---

## Installation

```bash
# Core (includes Ollama support — no API key needed)
pip install zonny-helper

# With Anthropic Claude
pip install "zonny-helper[anthropic]"

# With OpenAI GPT
pip install "zonny-helper[openai]"

# With Google Gemini
pip install "zonny-helper[gemini]"

# All cloud providers
pip install "zonny-helper[all]"
```

---

## Provider Setup

### Anthropic Claude
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### OpenAI GPT
```bash
export OPENAI_API_KEY="sk-..."
```

### Google Gemini
```bash
export GOOGLE_API_KEY="AIza..."
```

### Ollama (local, no API key)
```bash
# Install Ollama from https://ollama.com
ollama pull llama3
ollama serve   # runs at http://localhost:11434
```

Switch providers per-command:
```bash
zonny git commit --provider ollama
zonny tree build --provider anthropic
```

---

## Quick Start

### Git Workflow

```bash
# Stage changes and generate a commit message
git add src/payments/handler.py
zonny git commit

# Generate a PR description
zonny git pr --base main

# Generate a CHANGELOG from recent commits
zonny git changelog --from v0.9.0

# Diagnose a CI failure
zonny git whybroke --log ci_failure.log
```

### Codebase Intelligence

```bash
# Build the entity tree for your repository
zonny tree build --output tree.json

# Ask questions in plain English
zonny tree query "what writes to the transactions table?"
zonny tree query "what is called before sendEmail?"

# Compare two branches structurally
zonny tree diff main feature/checkout-v2

# Export as Markdown or Mermaid diagram
zonny tree export tree.json --format mermaid --output diagram.md
```

---

## Configuration

Copy `.zonny.toml.example` to `.zonny.toml` in your repository root:

```toml
[llm]
provider = "anthropic"   # or "openai" | "gemini" | "ollama"

[llm.anthropic]
model = "claude-sonnet-4-20250514"

[git]
commit_style = "conventional"
default_base_branch = "main"

[tree]
languages = ["python", "javascript", "typescript"]
enrich_by_default = true
```

Config priority (highest → lowest): CLI flags → environment variables → `.zonny.toml` → global config → defaults.

---

## Development

```bash
git clone https://github.com/yourusername/zonny-helper
cd zonny-helper

pip install -e ".[all,dev]"
pytest tests/ -v
ruff check src/
```

---

## Roadmap

- [x] Multi-provider LLM abstraction (Anthropic, OpenAI, Gemini, Ollama)
- [x] Configuration system with 4-level precedence
- [ ] `zonny git` — commit, pr, changelog, whybroke *(Phase 2)*
- [ ] `zonny tree build` — AST extraction + call graph *(Phase 3)*
- [ ] `zonny tree query/diff/export` — intelligence layer *(Phase 4)*
- [ ] VS Code extension
- [ ] GitHub Actions integration
- [ ] MCP Server mode

---

## License

MIT — see [LICENSE](LICENSE).
