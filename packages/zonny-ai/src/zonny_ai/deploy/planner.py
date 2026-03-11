"""zonny-ai deploy planner — LLM-powered strategy recommendation.

Reads .zonny/deploy-profile.json and uses the LLM to produce a ranked set
of deployment strategy recommendations with plain-English rationale.

Output is written to .zonny/deploy-plan.json and read by `zonny deploy generate`.
"""
from __future__ import annotations

import json
from pathlib import Path

from zonny_core.deploy.profile import DeployProfile

_PROFILE_PATH = Path(".zonny/deploy-profile.json")
_PLAN_PATH    = Path(".zonny/deploy-plan.json")


def plan_prompt(profile: DeployProfile) -> tuple[str, str]:
    """Build (system, user) prompt for deploy strategy planning."""
    system = (
        "You are a DevOps expert who recommends deployment strategies. "
        "Be concise and practical. Never recommend over-engineered solutions for simple apps. "
        "Output valid JSON with keys: recommended_target, strategy, rationale, alternatives."
    )
    user = f"""
Analyze this deployment profile and recommend the best strategy:

```json
{json.dumps(profile.to_dict(), indent=2)}
```

Respond with JSON:
{{
  "recommended_target": "<one of: docker|docker-compose|kubernetes|helm|ec2|ecs-fargate|lambda|fly.io|railway|cloud-run|azure-container|systemd|process>",
  "strategy": "<2-3 sentence summary of the recommended approach>",
  "rationale": "<why this target fits this project>",
  "alternatives": [
    {{"target": "...", "reason": "..."}}
  ],
  "warnings": ["<any caveats or things to watch out for>"]
}}
""".strip()
    return system, user


def run_planner(llm) -> None:  # type: ignore[type-arg]
    """Read the deploy profile, call LLM, write plan JSON.

    Parameters
    ----------
    llm:
        Any object conforming to the BaseLLMProvider interface from zonny-ai.
    """
    if not _PROFILE_PATH.exists():
        raise FileNotFoundError(
            f"Deploy profile not found at {_PROFILE_PATH}.\n"
            "Run `zonny deploy scan` first."
        )

    profile = DeployProfile.load(_PROFILE_PATH)
    system, prompt = plan_prompt(profile)
    response = llm.generate(prompt, system)

    # Parse and validate JSON response
    # Strip markdown code fences if the LLM wrapped the JSON
    clean = response.strip()
    if clean.startswith("```"):
        clean = "\n".join(clean.splitlines()[1:])
    if clean.endswith("```"):
        clean = "\n".join(clean.splitlines()[:-1])

    try:
        plan_data = json.loads(clean)
    except json.JSONDecodeError:
        # Fallback: wrap raw response
        plan_data = {
            "recommended_target": profile.deploy_targets[0] if profile.deploy_targets else "docker",
            "strategy": response[:500],
            "rationale": "LLM response was not valid JSON — using top-ranked target from scan.",
            "alternatives": [],
            "warnings": ["LLM returned non-JSON response; plan may need manual review."],
        }

    _PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PLAN_PATH.write_text(json.dumps(plan_data, indent=2), encoding="utf-8")
