"""Unit tests for the DeploymentAdvisor (advisor.py).

Tests cover:
  - advisor_prompt() — correct serialization of app and env profiles
  - deterministic_target() — all 11 rule branches
  - run_advisor() — happy path, bad JSON fallback, LLM exception fallback
  - _parse_memory_mb() helper
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from zonny_ai.deploy.advisor import (
    _parse_memory_mb,
    advisor_prompt,
    deterministic_target,
    run_advisor,
)
from zonny_core.deploy.env_scanner import EnvProfile
from zonny_core.deploy.profile import DeployProfile


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_app(**overrides) -> DeployProfile:
    defaults = dict(
        project="myapp",
        language="python",
        runtime="3.11",
        framework="fastapi",
        entry_point="main.py",
        port=8000,
        build_cmd="pip install -r requirements.txt",
        start_cmd="uvicorn main:app --host 0.0.0.0 --port 8000",
        databases=[],
        env_vars=["SECRET_KEY"],
        has_static=False,
        estimated_memory="256MB",
        deploy_targets=["docker", "docker-compose"],
        service_type="web",
    )
    defaults.update(overrides)
    return DeployProfile(**defaults)


def _all_false_tools() -> dict[str, bool]:
    return {
        "docker": False, "docker-compose": False, "kubectl": False, "helm": False,
        "flyctl": False, "railway": False, "gcloud": False, "aws": False,
        "az": False, "terraform": False, "heroku": False, "pulumi": False,
    }


def _make_env(**overrides) -> EnvProfile:
    defaults = dict(
        os="linux",
        arch="x86_64",
        cloud_context="local",
        tools=_all_false_tools(),
        docker_running=False,
        k8s_context=None,
        ram_gb=8.0,
        cpu_cores=4,
        disk_free_gb=50.0,
        ci=False,
        ci_provider=None,
    )
    defaults.update(overrides)
    return EnvProfile(**defaults)


def _mock_llm(response: str) -> MagicMock:
    llm = MagicMock()
    llm.generate.return_value = response
    llm.available.return_value = True
    return llm


# ── advisor_prompt ─────────────────────────────────────────────────────────────

class TestAdvisorPrompt:
    def test_returns_system_and_user_strings(self) -> None:
        system, user = advisor_prompt(_make_app(), _make_env())
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_lists_all_valid_targets(self) -> None:
        system, _ = advisor_prompt(_make_app(), _make_env())
        for target in ("docker", "fly.io", "railway", "cloud-run", "systemd", "process", "helm"):
            assert target in system

    def test_user_contains_project_name(self) -> None:
        _, user = advisor_prompt(_make_app(project="banana-api"), _make_env())
        assert "banana-api" in user

    def test_user_contains_env_info(self) -> None:
        _, user = advisor_prompt(_make_app(), _make_env(os="macos", cloud_context="local"))
        assert "macos" in user
        assert "local" in user

    def test_user_contains_memory_estimate(self) -> None:
        _, user = advisor_prompt(_make_app(estimated_memory="1GB"), _make_env())
        assert "1GB" in user

    def test_user_lists_available_tools(self) -> None:
        tools = {**_all_false_tools(), "flyctl": True, "gcloud": True}
        _, user = advisor_prompt(_make_app(), _make_env(tools=tools))
        assert "flyctl" in user
        assert "gcloud" in user


# ── _parse_memory_mb ───────────────────────────────────────────────────────────

class TestParseMemoryMb:
    def test_megabytes(self) -> None:
        assert _parse_memory_mb("256MB") == 256

    def test_gigabytes(self) -> None:
        assert _parse_memory_mb("1GB") == 1024

    def test_case_insensitive(self) -> None:
        assert _parse_memory_mb("512mb") == 512

    def test_unknown_defaults_to_512(self) -> None:
        assert _parse_memory_mb("unknown") == 512


# ── deterministic_target ───────────────────────────────────────────────────────

class TestDeterministicTarget:
    def test_no_docker_no_cloud_returns_process(self) -> None:
        rec = deterministic_target(_make_app(), _make_env())
        assert rec["target"] == "process"
        assert rec["via"] == "deterministic"

    def test_flyctl_small_app_returns_flyio(self) -> None:
        tools = {**_all_false_tools(), "flyctl": True}
        rec = deterministic_target(_make_app(estimated_memory="128MB"), _make_env(tools=tools))
        assert rec["target"] == "fly.io"

    def test_flyctl_large_app_does_not_return_flyio(self) -> None:
        tools = {**_all_false_tools(), "flyctl": True}
        rec = deterministic_target(_make_app(estimated_memory="1GB"), _make_env(tools=tools))
        assert rec["target"] != "fly.io"

    def test_gcloud_returns_cloud_run(self) -> None:
        tools = {**_all_false_tools(), "gcloud": True}
        rec = deterministic_target(_make_app(), _make_env(tools=tools))
        assert rec["target"] == "cloud-run"

    def test_kubectl_context_returns_kubernetes(self) -> None:
        rec = deterministic_target(
            _make_app(),
            _make_env(k8s_context="my-cluster"),
        )
        assert rec["target"] == "kubernetes"

    def test_railway_cli_returns_railway(self) -> None:
        tools = {**_all_false_tools(), "railway": True}
        rec = deterministic_target(_make_app(), _make_env(tools=tools))
        assert rec["target"] == "railway"

    def test_docker_running_with_databases_returns_compose(self) -> None:
        from zonny_core.deploy.profile import DBDependency  # noqa: PLC0415
        app = _make_app(databases=[DBDependency(type="postgresql", orm="sqlalchemy")])
        rec = deterministic_target(app, _make_env(docker_running=True))
        assert rec["target"] == "docker-compose"

    def test_docker_running_no_db_returns_docker(self) -> None:
        rec = deterministic_target(_make_app(), _make_env(docker_running=True))
        assert rec["target"] == "docker"

    def test_docker_running_worker_returns_compose(self) -> None:
        app = _make_app(service_type="worker")
        rec = deterministic_target(app, _make_env(docker_running=True))
        assert rec["target"] == "docker-compose"

    def test_linux_no_docker_no_cloud_returns_systemd(self) -> None:
        rec = deterministic_target(
            _make_app(),
            _make_env(os="linux", docker_running=False, tools=_all_false_tools()),
        )
        assert rec["target"] in ("systemd", "process")

    def test_ci_with_gcloud_returns_cloud_run(self) -> None:
        tools = {**_all_false_tools(), "gcloud": True}
        rec = deterministic_target(_make_app(), _make_env(ci=True, ci_provider="github-actions", tools=tools))
        assert rec["target"] == "cloud-run"

    def test_ci_no_gcloud_returns_ecs_fargate(self) -> None:
        rec = deterministic_target(_make_app(), _make_env(ci=True, ci_provider="github-actions"))
        assert rec["target"] == "ecs-fargate"

    def test_recommendation_has_all_required_keys(self) -> None:
        rec = deterministic_target(_make_app(), _make_env())
        assert "target" in rec
        assert "rationale" in rec
        assert "monthly_cost_usd" in rec
        assert "warnings" in rec
        assert "via" in rec

    def test_rationale_is_non_empty(self) -> None:
        rec = deterministic_target(_make_app(), _make_env())
        assert len(rec["rationale"]) > 10


# ── run_advisor ────────────────────────────────────────────────────────────────

class TestRunAdvisor:
    def test_happy_path_parses_llm_json(self) -> None:
        payload = json.dumps({
            "target": "fly.io",
            "rationale": "flyctl is installed and app is small.",
            "monthly_cost_usd": 0.0,
            "warnings": [],
        })
        llm = _mock_llm(payload)
        rec = run_advisor(llm, _make_app(), _make_env())
        assert rec["target"] == "fly.io"
        assert rec["via"] == "ai"

    def test_strips_markdown_fences(self) -> None:
        payload = "```json\n" + json.dumps({"target": "docker", "rationale": "x"}) + "\n```"
        llm = _mock_llm(payload)
        rec = run_advisor(llm, _make_app(), _make_env())
        assert rec["target"] == "docker"

    def test_fills_optional_keys_when_missing(self) -> None:
        payload = json.dumps({"target": "railway"})
        llm = _mock_llm(payload)
        rec = run_advisor(llm, _make_app(), _make_env())
        assert "rationale" in rec
        assert "monthly_cost_usd" in rec
        assert "warnings" in rec

    def test_falls_back_to_deterministic_on_bad_json(self) -> None:
        llm = _mock_llm("this is not JSON at all")
        rec = run_advisor(llm, _make_app(), _make_env())
        assert "target" in rec
        assert any("unavailable" in w.lower() or "deterministic" in w.lower()
                   for w in rec["warnings"])

    def test_falls_back_to_deterministic_on_llm_exception(self) -> None:
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("network error")
        rec = run_advisor(llm, _make_app(), _make_env())
        assert "target" in rec

    def test_falls_back_when_target_key_missing(self) -> None:
        payload = json.dumps({"rationale": "missing target key"})
        llm = _mock_llm(payload)
        rec = run_advisor(llm, _make_app(), _make_env())
        assert "target" in rec

    def test_monthly_cost_preserved_from_llm(self) -> None:
        payload = json.dumps({
            "target": "cloud-run",
            "rationale": "gcloud present",
            "monthly_cost_usd": 18.5,
            "warnings": [],
        })
        llm = _mock_llm(payload)
        rec = run_advisor(llm, _make_app(), _make_env())
        assert rec["monthly_cost_usd"] == 18.5

    def test_warnings_list_preserved(self) -> None:
        payload = json.dumps({
            "target": "kubernetes",
            "rationale": "cluster available",
            "monthly_cost_usd": None,
            "warnings": ["Ensure your cluster has sufficient resources"],
        })
        llm = _mock_llm(payload)
        rec = run_advisor(llm, _make_app(), _make_env())
        assert len(rec["warnings"]) == 1
        assert "Ensure" in rec["warnings"][0]

    def test_generates_prompt_with_correct_app_info(self) -> None:
        """Verify that the prompt passed to the LLM contains app profile data."""
        llm = _mock_llm(json.dumps({"target": "docker"}))
        app = _make_app(project="special-project", language="rust")
        run_advisor(llm, app, _make_env())
        call_args = llm.generate.call_args
        prompt_sent = call_args.args[0] if call_args.args else call_args[0][0]
        assert "special-project" in prompt_sent
        assert "rust" in prompt_sent
