# zonny

**One-command deploy automation, Cloudflare tunnel publishing, and AI-powered developer tooling.**

```bash
pip install zonny
```

## What it does

```bash
# Scan your project and detect its deploy profile
zonny deploy scan .

# Generate Dockerfile, docker-compose, process configs
zonny deploy generate

# Run it locally
zonny deploy run

# Publish to the internet via your existing Cloudflare tunnel — one command,
# fully automated: ingress rule + DNS CNAME + cloudflared started + URL verified
zonny deploy cloudflare --tunnel MyTunnel --port 8000

# AI git commit — stages diff, writes commit message, runs git commit
zonny git commit

# AI PR description, changelog, whybroke analysis
zonny git pr
zonny git changelog
zonny git whybroke
```

## Install

```bash
# Core + AI features (everything)
pip install zonny

# With a specific LLM provider
pip install "zonny[anthropic]"
pip install "zonny[openai]"
pip install "zonny[gemini]"
pip install "zonny[all]"       # all providers
```

## Packages

| Package | What it contains |
|---|---|
| `zonny-core` | Deploy scanner, generator, runner, Cloudflare automation, git tools, tree builder, config system |
| `zonny-ai` | LLM providers (Ollama, Anthropic, OpenAI, Gemini), AI git commands, AI deploy planning |
| `zonny` | Meta-package — installs both |

## Cloudflare one-command publish

```bash
# One-time setup: create a Custom Token at dash.cloudflare.com/profile/api-tokens
# Permissions: Account > Cloudflare Tunnel > Edit  +  Zone > DNS > Edit
zonny config set cloudflare.api_token <YOUR_TOKEN>

# Then just run:
zonny deploy cloudflare --tunnel MyTunnel --port 8000
# [1/6] Detecting tunnel...
# [2/6] Publishing to: https://p8000.yourdomain.com
# [3/6] Ingress rule saved
# [4/6] DNS record live
# [5/6] cloudflared running and connected
# [6/6] Live: https://p8000.yourdomain.com
```

## Links

- [GitHub](https://github.com/Saridena/zonny)
- [Issues](https://github.com/Saridena/zonny/issues)
