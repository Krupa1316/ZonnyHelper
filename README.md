# Zonny-Helper

[![PyPI](https://img.shields.io/pypi/v/zonny.svg)](https://pypi.org/project/zonny/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![Status: Beta](https://img.shields.io/badge/status-beta-yellow.svg)](https://pypi.org/project/zonny/)

> **We are looking contributors.**
> If you try Zonny and run into anything — bugs, confusing output, missing features — please [open an issue](https://github.com/Saridena/zonny/issues).
> If you want to contribute code, see the [Contributing](#contributing) section at the bottom.

---

A developer CLI for deploying applications, automating git workflows, and mapping codebases — with optional AI assistance from any provider you already use.

```
pip install zonny
```

## What's Coming Next

These features are designed and partially scoped — they are the highest-value things left to build. If any of these match something you want to work on, open an issue and let's talk.

---

### `zonny deploy plan` (AI strategy advisor)

The missing step between `scan` and `generate`. Today you run `scan` which produces a profile, then choose a target yourself. `plan` will read the profile and the environment (`zonny deploy env`) together and use AI to recommend the best deploy strategy — including why, what trade-offs exist, and what prerequisites are needed.

```bash
zonny deploy plan
# Output: recommended target, alternatives ranked, one-line reason for each
# Writes: .zonny/deploy-plan.json (already read by `generate` if present)
```

The `generate` command already reads `.zonny/deploy-plan.json` if it exists — the planner just needs to write it.

**Contribution area:** `packages/zonny-ai/src/zonny_ai/deploy/planner.py` — the stub is there, needs the prompt and the output schema.

---

### `zonny deploy diagnose` (AI root cause from failed deployments)

Different from `zonny git whybroke` (which reads CI logs). `diagnose` reads `.zonny/last-error.log` — the file written by `zonny deploy run` on failure — and asks the AI what went wrong at the infrastructure level: missing env vars, port conflicts, image pull failures, OOM kills, etc.

```bash
zonny deploy diagnose
# Reads: .zonny/last-error.log (written automatically on deploy failure)
# Output: root cause, specific fix command or config change, optional auto-patch
```

The log file and the deploy profile together give the AI enough context to give specific, actionable answers rather than generic advice.

**Contribution area:** `packages/zonny-ai/src/zonny_ai/deploy/commands.py` — `diagnose` command + prompt in `packages/zonny-ai/src/zonny_ai/llm/prompts.py`.

---

### `zonny deploy nginx` (Nginx Proxy Manager integration)

A companion to `zonny deploy cloudflare` for people running their own servers. If you have Nginx Proxy Manager running (common on home servers and VPS setups), Zonny should be able to create the proxy host automatically via NPM's REST API — same automation, different backend.

```bash
zonny deploy nginx --port 8000 --domain app.yourdomain.com --npm-url http://localhost:81
```

One-time setup:
```bash
zonny config set nginx.url http://localhost:81
zonny config set nginx.email admin@yourdomain.com
zonny config set nginx.password yourpassword
```

Then a single command creates the proxy host, sets up SSL via Let's Encrypt, and prints the live URL — no manual NPM UI interaction.

**Contribution area:** New file `packages/zonny-core/src/zonny_core/deploy/nginx.py` + command registration in `deploy/commands.py`.

---

### `zonny tree enrich` (AI semantic labeling)

`zonny tree build` gives you the structural skeleton — functions, classes, imports. `enrich` goes further: it reads the entity tree and uses AI to label the *purpose and flow* of each entity. What does this function actually do? What domain concept does it represent? Which entities form a logical pipeline?

```bash
zonny tree build
zonny tree enrich
# Adds semantic labels, flow tags, and domain classification to .zonny/tree.json
# Enables natural language queries and agent context output
```

Without enrichment, `query` and `context` (below) operate on structure only. With enrichment, they operate on meaning.

**Contribution area:** `packages/zonny-ai/src/zonny_ai/tree/` — enrichment loop, chunking strategy, prompt design.

---

### `zonny tree query` (natural language questions)

Once the tree is built (and optionally enriched), ask questions in plain English:

```bash
zonny tree query "what writes to the transactions table?"
zonny tree query "what is called before sendEmail?"
zonny tree query "which functions handle authentication?"
```

The command converts the question to a structured lookup over the entity graph, optionally using AI to interpret ambiguous queries. Results show entity names, file paths, and line numbers.

**Contribution area:** `packages/zonny-ai/src/zonny_ai/tree/commands.py` — the command skeleton exists, needs the query engine and prompt.

---

### `zonny tree context` (AI agent context document)

A compressed, token-efficient representation of the codebase designed to be injected into an AI agent's context window. Instead of feeding raw source files, this outputs a structured document that covers every file's purpose, key entities, and relationships — in a fraction of the tokens.

```bash
zonny tree context --output context.md
zonny tree context --format json --max-tokens 8000
```

The output is optimised for agents: it omits implementation details and focuses on interfaces, data flows, and architectural boundaries. Useful for giving an AI assistant a working understanding of an unfamiliar codebase instantly.

**Contribution area:** New subcommand under `zonny tree`. Needs a compression strategy and a format spec that balances coverage against token budget.

---

## Table of Contents

- [Installation](#installation)
- [Packages](#packages)
- [Configuration](#configuration)
  - [API Keys](#api-keys)
  - [Defaults](#defaults)
  - [Config Commands](#config-commands)
- [Deploy Commands](#deploy-commands)
  - [scan](#zonny-deploy-scan)
  - [generate](#zonny-deploy-generate)
  - [run](#zonny-deploy-run)
  - [status](#zonny-deploy-status)
  - [rollback](#zonny-deploy-rollback)
  - [env](#zonny-deploy-env)
  - [history](#zonny-deploy-history)
  - [tunnels](#zonny-deploy-tunnels)
  - [cloudflare](#zonny-deploy-cloudflare)
- [Git Commands](#git-commands)
  - [diff](#zonny-git-diff)
  - [log](#zonny-git-log)
  - [commit (AI)](#zonny-git-commit-ai)
  - [pr (AI)](#zonny-git-pr-ai)
  - [changelog (AI)](#zonny-git-changelog-ai)
  - [whybroke (AI)](#zonny-git-whybroke-ai)
- [Tree Commands](#tree-commands)
  - [build](#zonny-tree-build)
  - [diff](#zonny-tree-diff)
  - [export](#zonny-tree-export)
- [LLM Providers](#llm-providers)
- [Testing](#testing)
- [What's Coming Next](#whats-coming-next)
- [Contributing](#contributing)

---

## Installation

```bash
# Full install — includes deploy, git automation, AI commands, and all providers
pip install zonny

# Core only — deployer, git tools, tree builder (no AI, no API keys needed)
pip install zonny-core

# With a specific AI provider
pip install "zonny[anthropic]"
pip install "zonny[openai]"
pip install "zonny[gemini]"

# All AI providers
pip install "zonny[all]"
```

Verify the install:

```bash
zonny --version
```

---

## Packages

Zonny is split into two packages. Both are installed when you run `pip install zonny`.

| Package | Contents |
|---|---|
| `zonny-core` | Deploy pipeline, git diff tools, codebase tree builder, config manager |
| `zonny-ai` | AI git commands (commit, pr, changelog, whybroke), AI deploy advisor, LLM providers |

If you do not need AI features, `pip install zonny-core` is sufficient and has no API key requirement.

---

## Configuration

All configuration is stored in `~/.zonny/config.toml`. The file is created automatically on first use. Keys are stored with `600` permissions (owner read/write only) so they are not accidentally committed.

### API Keys

Set keys using the CLI — do not edit the file by hand:

```bash
zonny config set-key anthropic  sk-ant-api03-...
zonny config set-key openai     sk-proj-...
zonny config set-key gemini     AIza...
```

For Ollama (local, no key needed), just make sure Ollama is running — see [LLM Providers](#llm-providers).

Remove a key:

```bash
zonny config unset-key anthropic
```

### Defaults

```bash
# Set which AI provider to use by default
zonny config set defaults.ai_provider anthropic

# Set default deploy target
zonny config set defaults.deploy_target docker-compose
```

### Config Commands

| Command | Description |
|---|---|
| `zonny config set-key <provider> <key>` | Store an API key |
| `zonny config unset-key <provider>` | Remove a stored key |
| `zonny config list` | Show all keys (masked) and current defaults |
| `zonny config set <section.key> <value>` | Set any config value with dot notation |
| `zonny config get <section.key>` | Read a single config value |

Example — check what is set:

```bash
zonny config list
```

---

## Deploy Commands

The deploy pipeline follows a fixed sequence: **scan → generate → run**. Each step reads the output of the previous one.

---

### `zonny deploy scan`

Scans a project directory and auto-detects everything needed to deploy it: language, framework, entry point, port, database dependencies, environment variables, estimated memory, and recommended deploy targets.

```bash
zonny deploy scan .
zonny deploy scan /path/to/project
```

**Options:**

| Flag | Description |
|---|---|
| `--output <path>` / `-o` | Write profile JSON to a custom path (default: `.zonny/deploy-profile.json`) |
| `--show` / `-s` | Print the full profile JSON after scanning |

After scanning, a table is printed with the detected profile. The profile is written to `.zonny/deploy-profile.json` and used by all subsequent deploy commands.

---

### `zonny deploy generate`

Reads the deploy profile and generates the deployment configuration files (Dockerfile, docker-compose.yml, Kubernetes YAMLs, fly.toml, etc.).

```bash
zonny deploy generate
zonny deploy generate --target docker-compose
zonny deploy generate --target kubernetes
```

**Supported targets:**

`docker`, `docker-compose`, `kubernetes`, `ecs-fargate`, `ec2`, `lambda`, `fly.io`, `railway`, `cloud-run`, `systemd`, `process`, `helm`

**Options:**

| Flag | Description |
|---|---|
| `--target <name>` / `-t` | Which target to generate for. Reads from AI plan if omitted, then falls back to top suggestion from scan |
| `--profile <path>` | Custom path to deploy profile JSON |
| `--out <dir>` | Output directory (default: `.zonny/generated/`) |

Generated files are printed on completion. The next step is `zonny deploy run --target <same target>`.

---

### `zonny deploy run`

Executes the generated deployment configuration with live log streaming.

```bash
zonny deploy run
zonny deploy run --target docker-compose
zonny deploy run --target process
zonny deploy run --dry-run
```

**Options:**

| Flag | Description |
|---|---|
| `--target <name>` / `-t` | Target to run (inferred from profile if omitted) |
| `--profile <path>` | Custom profile path |
| `--dir <path>` | Directory containing generated config files (default: `.zonny/generated/`) |
| `--dry-run` | Print the deployment commands without executing them |

On success, the app URL is printed (`http://localhost:<port>`). On failure, the error log is written to `.zonny/last-error.log`.

---

### `zonny deploy status`

Shows the running state of the deployed application.

```bash
zonny deploy status
zonny deploy status --target kubernetes
```

For `docker` and `docker-compose` targets, runs `docker ps` filtered by project name. For `kubernetes`, runs `kubectl get pods`. Other targets print a warning that live status is not available.

---

### `zonny deploy rollback`

Reverts to the previous deployment state.

```bash
zonny deploy rollback
zonny deploy rollback --target kubernetes
```

For `docker-compose`, runs `docker compose down` then brings the previous image back up. For `kubernetes`, runs `kubectl rollout undo`. Other targets print instructions to restore manually from git or a snapshot.

---

### `zonny deploy env`

Scans the current machine and shows what is installed and what is available for deployment.

```bash
zonny deploy env
```

Detects: OS and architecture, cloud context (EC2 / GCP / Azure / local), CI provider, Docker daemon state, Kubernetes context, AWS region, GCP project, Azure subscription, RAM, CPU cores, disk space, and which CLI tools are installed or missing.

---

### `zonny deploy history`

Shows recent deployment history from `.zonny/history.json`.

```bash
zonny deploy history
zonny deploy history --limit 20
zonny deploy history --json
```

**Options:**

| Flag | Description |
|---|---|
| `--limit <n>` / `-n` | Number of entries to show (default: 10) |
| `--json` | Print raw JSON |
| `<path>` | Argument — project directory (default: `.`) |

The table shows timestamp, project name, target, status (success / failed), number of self-healing attempts, duration, and how the deployment was triggered. Entries with failures show fix suggestions inline.

---

### `zonny deploy tunnels`

Lists Cloudflare Tunnels detected on the current machine.

```bash
zonny deploy tunnels
```

Requires `cloudflared` to be installed. Shows tunnel name, ID, whether credentials exist, and whether a token is available. If no tunnels are found, it prints instructions to run `cloudflared login`.

---

### `zonny deploy cloudflare`

Publishes a running local app to the internet through a Cloudflare Tunnel. Fully automated — no manual `cloudflared` config needed.

```bash
zonny deploy cloudflare --tunnel MyTunnel --port 8000
```

**One-time setup required:**

1. Go to [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Create a token with these permissions:
   - `Account > Cloudflare Tunnel > Edit`
   - `Zone > DNS > Edit`
3. Save it:

```bash
zonny config set cloudflare.api_token <YOUR_TOKEN>
```

After that, the command handles everything automatically:

```
[1/6] Detect tunnel and extract credentials
[2/6] Determine public hostname
[3/6] Add / update ingress rule via Cloudflare API
[4/6] Create / update DNS CNAME via Cloudflare API
[5/6] Start cloudflared and connect to Cloudflare edge
[6/6] Verify URL is live
```

**Options:**

| Flag | Description |
|---|---|
| `--port <n>` / `-p` | Local port to expose. Reads from deploy profile if omitted, defaults to 8000 |
| `--tunnel <name>` / `-t` | Tunnel name to use. Auto-selects if omitted |
| `--hostname <host>` / `-H` | Full public hostname (e.g. `app.yourdomain.com`). Auto-derived from tunnel routes if omitted |
| `--profile <path>` | Custom profile path |

The public URL is printed when live. The tunnel runs until you press `Ctrl+C`.

---

## Git Commands

---

### `zonny git diff`

Shows the current git diff.

```bash
zonny git diff
zonny git diff --base main
zonny git diff --stat
```

**Options:**

| Flag | Description |
|---|---|
| `--cached` / `--working` | Show staged diff (default) or working-tree diff |
| `--base <branch>` / `-b` | Compare current branch against this branch instead of staged diff |
| `--stat` | Show a summary (files changed, insertions, deletions) instead of the full diff |

---

### `zonny git log`

Shows the commit log for a ref range.

```bash
zonny git log
zonny git log --from v1.0.0 --to HEAD --num 30
```

**Options:**

| Flag | Description |
|---|---|
| `--from <ref>` | Start ref — tag or commit SHA |
| `--to <ref>` | End ref (default: `HEAD`) |
| `--num <n>` / `-n` | Max commits to display (default: 20) |

---

### `zonny git commit` (AI)

Generates a [Conventional Commit](https://www.conventionalcommits.org/) message from your staged diff and optionally runs `git commit` automatically. Requires `zonny-ai`.

```bash
# Preview only
git add .
zonny git commit

# Generate and commit in one step
zonny git commit --execute

# Hint the commit type and scope
zonny git commit --type feat --scope auth --execute

# Use a specific AI provider
zonny git commit --provider ollama
```

**Options:**

| Flag | Description |
|---|---|
| `--dry-run` / `-n` | Show the message but do not commit |
| `--execute` / `-e` | Run `git commit -m <message>` automatically after generating |
| `--type <type>` / `-t` | Hint the commit type (feat, fix, chore, docs, refactor, …) |
| `--scope <scope>` / `-s` | Hint the scope (e.g. `payments`, `auth`) |
| `--provider <name>` / `-p` | LLM provider override (`anthropic`, `openai`, `gemini`, `ollama`) |
| `--json` | Output as JSON |

You must run `git add` first. The command exits with an error if there are no staged changes.

---

### `zonny git pr` (AI)

Generates a GitHub Pull Request description from the branch diff. Requires `zonny-ai`.

```bash
zonny git pr
zonny git pr --base develop
zonny git pr --template .github/pull_request_template.md
```

**Options:**

| Flag | Description |
|---|---|
| `--base <branch>` / `-b` | Branch to diff against (default: `main`) |
| `--template <path>` | Path to a PR template file — its content is appended to the prompt |
| `--provider <name>` / `-p` | LLM provider override |
| `--json` | Output as JSON |

The output includes Summary, Changes, Testing, and Breaking Changes sections, ready to paste into a GitHub PR.

---

### `zonny git changelog` (AI)

Generates a CHANGELOG entry from the git log between two refs. Requires `zonny-ai`.

```bash
zonny git changelog --from v1.0.0
zonny git changelog --from v1.0.0 --to v1.1.0
zonny git changelog --from v1.0.0 --output CHANGELOG.md
```

**Options:**

| Flag | Description |
|---|---|
| `--from <ref>` | Start ref — tag or commit SHA (required) |
| `--to <ref>` | End ref (default: `HEAD`) |
| `--output <path>` / `-o` | Append the generated section to this file |
| `--provider <name>` / `-p` | LLM provider override |
| `--json` | Output as JSON |

---

### `zonny git whybroke` (AI)

Diagnoses a CI failure from a log file and the recent diff. Requires `zonny-ai`.

```bash
zonny git whybroke --log ci_failure.log
zonny git whybroke --log ci_failure.log --provider anthropic
```

**Options:**

| Flag | Description |
|---|---|
| `--log <path>` | Path to the CI failure log file (required) |
| `--provider <name>` / `-p` | LLM provider override |
| `--json` | Output as JSON |

The output explains what went wrong, which commit likely caused it, and what to fix.

---

## Tree Commands

The tree builder parses your codebase into a structured entity map (functions, classes, imports, DB calls). Supports 20+ languages using tree-sitter with regex fallback for unknown languages.

---

### `zonny tree build`

Parses the repository and writes a tree JSON file.

```bash
zonny tree build
zonny tree build /path/to/project --output .zonny/tree.json
zonny tree build --languages python,typescript
zonny tree build --max-depth 4
```

**Options:**

| Flag | Description |
|---|---|
| `<root>` | Repository root directory (default: `.`) |
| `--output <path>` / `-o` | Where to write the tree JSON (default: `.zonny/tree.json`) |
| `--languages <list>` | Comma-separated language filter, e.g. `python,javascript`. Leave empty to parse all |
| `--max-depth <n>` | Maximum directory depth to scan |
| `--json` | Print the full tree as JSON to stdout instead of a summary |

After building, the tree is ready to diff or export. For semantic enrichment, run `zonny tree enrich` (requires `zonny-ai`).

---

### `zonny tree diff`

Compares the entity tree between two branches or commits and shows what changed structurally.

```bash
zonny tree diff main feature/new-checkout
zonny tree diff v1.0.0 v1.1.0
```

Shows added, removed, and modified functions, classes, and other entities.

---

### `zonny tree export`

Exports the tree in a human-readable or visual format.

```bash
zonny tree export .zonny/tree.json
zonny tree export .zonny/tree.json --format mermaid --output diagram.md
zonny tree export .zonny/tree.json --format markdown
```

**Options:**

| Flag | Description |
|---|---|
| `<path>` | Path to the tree JSON file |
| `--format <fmt>` | Output format: `mermaid`, `markdown`, `json` |
| `--output <path>` / `-o` | Write to file instead of stdout |

---

## LLM Providers

All AI commands (`zonny git commit`, `zonny git pr`, `zonny git changelog`, `zonny git whybroke`) and AI deploy advisor commands use one of four providers.

### Ollama (local, no API key)

Install from [ollama.com](https://ollama.com), then:

```bash
ollama pull llama3
ollama serve
```

Ollama runs at `http://localhost:11434` by default. Select it:

```bash
zonny config set defaults.ai_provider ollama
# or per-command:
zonny git commit --provider ollama
```

### Anthropic Claude

```bash
zonny config set-key anthropic sk-ant-api03-...
zonny config set defaults.ai_provider anthropic
```

### OpenAI

```bash
zonny config set-key openai sk-proj-...
zonny config set defaults.ai_provider openai
```

### Google Gemini

```bash
zonny config set-key gemini AIza...
zonny config set defaults.ai_provider gemini
```

### Provider priority

The provider used for each command follows this order (first match wins):

1. `--provider` flag on the command
2. `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` environment variables
3. `defaults.ai_provider` in `~/.zonny/config.toml`
4. Falls back to Ollama if nothing is configured

---

## Testing

This project is in beta. If you install and try it, please share what you find.

**Things to try:**

```bash
# Run it against a real project you have locally
cd /your/project
zonny deploy scan .
zonny deploy generate
zonny deploy env

# Test git automation on a branch with staged changes
git add .
zonny git commit --dry-run

# Test the Cloudflare tunnel if you have a Cloudflare account
zonny deploy tunnels
zonny deploy cloudflare --port 3000

# Check the version
zonny --version
```

**If you find a bug or unexpected output**, open an issue at [github.com/Saridena/zonny/issues](https://github.com/Saridena/zonny/issues) with:
- The command you ran
- The output or error
- OS and Python version

---

## Contributing

Contributions are welcome. The project is structured as a monorepo with two packages.

**Repository layout:**

```
packages/zonny-core/    — deploy pipeline, config, tree builder, git utils
packages/zonny-ai/      — LLM providers, AI commands, AI deploy advisor
packages/zonny/         — meta-package (depends on both)
tests/unit/             — unit tests
tests/integration/      — integration tests
```

**Setup:**

```bash
git clone https://github.com/Saridena/zonny
cd zonny

pip install -e "packages/zonny-core[dev]"
pip install -e "packages/zonny-ai[dev]"

pytest tests/ -q
```

**Before submitting a PR:**

```bash
ruff check packages/
pytest tests/ -q
```

Areas where contributions would be most useful:

- Implement any of the features in [What's Coming Next](#whats-coming-next) — each section links directly to the relevant files
- New deploy targets (Railway, Fly.io edge cases, bare EC2 setup, bare VPS with systemd)
- Nginx Proxy Manager integration (`packages/zonny-core/src/zonny_core/deploy/nginx.py`)
- AI deploy planner (`packages/zonny-ai/src/zonny_ai/deploy/planner.py` — stub exists)
- AI deploy diagnose command (`packages/zonny-ai/src/zonny_ai/deploy/commands.py`)
- Tree enrich, query, and context commands (`packages/zonny-ai/src/zonny_ai/tree/`)
- Language support in the tree builder (new tree-sitter parsers or regex patterns)
- Improved AI prompts for commit, PR, and changelog generation
- Windows-specific fixes in the deploy runner and cloudflared integration
- Test coverage for integration scenarios

Open an issue before starting large changes so we can discuss the approach first.

---

## License

MIT — see [LICENSE](LICENSE).
