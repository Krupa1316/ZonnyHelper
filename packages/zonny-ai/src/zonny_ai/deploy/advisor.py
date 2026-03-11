"""DeploymentAdvisor — AI-powered target recommendation (Condition 2).

Takes an AppProfile + EnvProfile and recommends the single best deployment
target, with rationale and monthly cost estimate.

Two paths:
  1. AI path  — calls the LLM with advisor_prompt(); parses JSON response.
  2. Fallback — deterministic_target() rules; used when no LLM is available
               or when --no-ai flag is passed.

Output schema (dict):
  {
    "target":             str,          # e.g. "fly.io"
    "rationale":          str,          # plain-English explanation
    "monthly_cost_usd":   float | None, # rough estimate, None if unknown
    "warnings":           list[str],    # anything the user should know
    "via":                str,          # "ai" | "deterministic"
  }
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zonny_ai.llm.base import BaseLLMProvider
    from zonny_core.deploy.env_scanner import EnvProfile
    from zonny_core.deploy.profile import DeployProfile


# ── Prompt builder ─────────────────────────────────────────────────────────────

def advisor_prompt(app: "DeployProfile", env: "EnvProfile") -> tuple[str, str]:
    """Build (system, user) prompt for the DeploymentAdvisor (Condition 2)."""
    system = """\
You are a DevOps deployment advisor. Your job is to recommend the SINGLE best
deployment target for a given application and environment.

Valid targets (pick exactly one):
  docker, docker-compose, kubernetes, helm,
  ec2, ecs-fargate, lambda,
  fly.io, railway, cloud-run, azure-container,
  systemd, process

Rules (apply in order — first rule that matches wins):
1. If docker is NOT running AND no cloud CLI is installed → "process"
2. If running in GitHub Actions → "ecs-fargate" (or "cloud-run" if gcloud present)
3. If flyctl is installed AND estimated_memory <= 256MB → "fly.io"  (free tier)
4. If gcloud is installed AND cloud_context is "gcp-gce" or "local" → "cloud-run"
5. If kubectl has an active context → "kubernetes"
6. If railway CLI is installed → "railway"
7. If docker is running AND service_type is "worker" → "docker-compose"
8. If docker is running AND app has databases → "docker-compose"
9. If docker is running → "docker"
10. If OS is Linux AND no docker AND no cloud CLI → "systemd"
11. Fallback → "process"

Never recommend:
- kubernetes for a solo project with 1 service and < 3 replicas needed
- lambda for apps with service_type "worker" or "static"
- fly.io if estimated_memory > 512MB (exceeds free tier)

Output ONLY valid JSON — no markdown, no prose:
{
  "target": "<target>",
  "rationale": "<1-2 sentences explaining why>",
  "monthly_cost_usd": <number or null>,
  "warnings": ["<optional caveats>"]
}
"""

    # Serialize the profiles compactly
    app_dict = {
        "project":          app.project,
        "language":         app.language,
        "framework":        app.framework,
        "service_type":     getattr(app, "service_type", "web"),
        "port":             app.port,
        "databases":        [d.type for d in app.databases],
        "estimated_memory": app.estimated_memory,
        "deploy_targets":   app.deploy_targets[:4],   # top 4 from scanner ranking
    }
    env_dict = {
        "os":             env.os,
        "arch":           env.arch,
        "cloud_context":  env.cloud_context,
        "docker_running": env.docker_running,
        "k8s_context":    env.k8s_context,
        "ci":             env.ci,
        "ci_provider":    env.ci_provider,
        "ram_gb":         env.ram_gb,
        "tools_available": [t for t, ok in env.tools.items() if ok],
    }

    user = f"""\
App profile:
{json.dumps(app_dict, indent=2)}

Environment profile:
{json.dumps(env_dict, indent=2)}

Based on the above, recommend the SINGLE best deployment target.
"""
    return system, user


# ── Deterministic fallback ─────────────────────────────────────────────────────

def deterministic_target(
    app: "DeployProfile",
    env: "EnvProfile",
) -> dict:
    """Return a recommendation without calling the LLM.

    Implements the same rule set as the advisor system prompt but in Python,
    used when --no-ai is passed or when the LLM is unavailable.
    """
    tools = env.tools
    memory_mb = _parse_memory_mb(app.estimated_memory)

    # Helpers
    def has(t: str) -> bool:
        return tools.get(t, False)

    # Rule 2 — CI environment (checked before no-cloud fallback so CI + no tools still routes correctly)
    if env.ci:
        if has("gcloud"):
            return _rec("cloud-run", "Running in CI with gcloud installed — Cloud Run is the best PaaS target.", 20.0, [], "deterministic")
        return _rec("ecs-fargate", "Running in CI — ECS Fargate is a reliable serverless container target.", 30.0, [], "deterministic")

    # Rule 1 — no docker, no cloud CLI, no k8s context at all
    has_cloud = (
        any(has(t) for t in ("gcloud", "aws", "az", "flyctl", "railway"))
        or bool(env.k8s_context)
    )
    if not env.docker_running and not has_cloud:
        return _rec("process", "No Docker daemon and no cloud CLI found — plain process is the only option.", 0.0, [], "deterministic")

    # Rule 3 — flyctl + small app
    if has("flyctl") and memory_mb <= 256:
        return _rec("fly.io", "flyctl is installed and the app is small — Fly.io free tier is ideal.", 0.0, [], "deterministic")

    # Rule 4 — gcloud
    if has("gcloud"):
        return _rec("cloud-run", "gcloud is installed — Cloud Run offers serverless scaling with no infrastructure to manage.", 15.0, [], "deterministic")

    # Rule 5 — kubectl active
    if env.k8s_context:
        return _rec("kubernetes", f"Active kubectl context '{env.k8s_context}' found — deploy directly to your cluster.", None, ["Ensure your cluster has sufficient resources"], "deterministic")

    # Rule 6 — railway CLI
    if has("railway"):
        return _rec("railway", "railway CLI is installed — Railway offers zero-config deployments.", 5.0, [], "deterministic")

    service_type = getattr(app, "service_type", "web")

    # Rule 7 — docker + worker
    if env.docker_running and service_type == "worker":
        return _rec("docker-compose", "Worker service with Docker running — docker-compose manages worker + dependencies cleanly.", 0.0, [], "deterministic")

    # Rule 8 — docker + databases
    if env.docker_running and app.databases:
        return _rec("docker-compose", f"App has {len(app.databases)} database dependency(-ies) — docker-compose handles the full stack.", 0.0, [], "deterministic")

    # Rule 9 — docker running
    if env.docker_running:
        return _rec("docker", "Docker is running — container deployment is the simplest reliable option.", 0.0, [], "deterministic")

    # Rule 10 — Linux + systemd
    if env.os == "linux" and not env.docker_running and not has("gcloud") and not has("flyctl"):
        return _rec("systemd", "Linux host without Docker or cloud CLIs — systemd service is the lightest deployment.", 0.0, [], "deterministic")

    # Fallback
    return _rec("process", "No matching environment signals — plain process deployment is the safest fallback.", 0.0, ["Install Docker or a cloud CLI for better deployment options"], "deterministic")


def _rec(target: str, rationale: str, cost: float | None, warnings: list[str], via: str) -> dict:
    return {
        "target":           target,
        "rationale":        rationale,
        "monthly_cost_usd": cost,
        "warnings":         warnings,
        "via":              via,
    }


def _parse_memory_mb(mem_str: str) -> int:
    """Parse '512MB' or '1GB' → integer MB."""
    s = mem_str.upper().strip()
    if s.endswith("GB"):
        return int(s[:-2]) * 1024
    if s.endswith("MB"):
        return int(s[:-2])
    return 512  # safe default


# ── Public API ─────────────────────────────────────────────────────────────────

def run_advisor(
    llm: "BaseLLMProvider",
    app: "DeployProfile",
    env: "EnvProfile",
) -> dict:
    """Call the LLM advisor and parse the result.

    Falls back to deterministic_target() if the LLM returns invalid JSON or
    is unavailable.

    Returns a recommendation dict (see module docstring for schema).
    """
    system, user = advisor_prompt(app, env)

    try:
        response = llm.generate(user, system, max_tokens=512)
        clean = response.strip()
        # Strip markdown fences if the model wrapped the JSON
        if clean.startswith("```"):
            lines = clean.splitlines()
            clean = "\n".join(lines[1:] if lines[0].startswith("```") else lines)
        if clean.endswith("```"):
            clean = "\n".join(clean.splitlines()[:-1])

        rec = json.loads(clean)

        # Validate required keys
        if "target" not in rec:
            raise ValueError("Missing 'target' key in LLM response")

        rec.setdefault("rationale", "")
        rec.setdefault("monthly_cost_usd", None)
        rec.setdefault("warnings", [])
        rec["via"] = "ai"
        return rec

    except Exception:  # noqa: BLE001
        # LLM unavailable or returned bad JSON — fall back to deterministic
        result = deterministic_target(app, env)
        result["warnings"].append("AI advisor unavailable — used deterministic rules.")
        return result
