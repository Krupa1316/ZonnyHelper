"""Unit tests for the deploy runner (runner.py).

All tests patch `_run_streaming` so no real tools (docker, flyctl, etc.)
are required on the test host.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from zonny_core.deploy.profile import DeployProfile
from zonny_core.deploy.runner import DeployError, run


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_profile(**overrides) -> DeployProfile:
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
        estimated_memory="512MB",
        deploy_targets=["docker"],
    )
    defaults.update(overrides)
    return DeployProfile(**defaults)


PATCH = "zonny_core.deploy.runner._run_streaming"


# ── Dispatch ───────────────────────────────────────────────────────────────────

class TestRunDispatch:
    def test_unknown_target_raises_deploy_error(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with pytest.raises(DeployError, match="No runner for target"):
            run(profile, "nonexistent-target", tmp_path)

    def test_all_known_targets_are_dispatched(self, tmp_path: Path) -> None:
        """Smoke-test that every valid target string has a runner registered."""
        known = [
            "docker", "docker-compose", "kubernetes", "helm",
            "ec2", "ecs-fargate", "lambda",
            "fly.io", "railway", "cloud-run", "azure-container",
            "systemd", "process",
        ]
        profile = _make_profile()
        # Create stub files that some runners check for
        (tmp_path / "run.sh").write_text("#!/bin/bash\necho hi\n")
        (tmp_path / f"{profile.project}.service").write_text("[Unit]\n")
        helm_dir = tmp_path / "helm" / profile.project
        helm_dir.mkdir(parents=True)

        with patch(PATCH, return_value="") as mock_stream:
            for target in known:
                mock_stream.reset_mock()
                if target == "ec2":
                    # ec2 intentionally raises to guide manual provisioning
                    with pytest.raises(DeployError):
                        run(profile, target, tmp_path)
                else:
                    run(profile, target, tmp_path)
                    mock_stream.assert_called()


# ── docker ─────────────────────────────────────────────────────────────────────

class TestDockerRunner:
    def test_builds_and_runs_container(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "docker", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("build" in c for c in calls)
        assert any("run" in c for c in calls)

    def test_docker_run_maps_port(self, tmp_path: Path) -> None:
        profile = _make_profile(port=9000)
        with patch(PATCH, return_value="") as mock:
            run(profile, "docker", tmp_path)
        all_args = [arg for c in mock.call_args_list for arg in c.args[0]]
        assert "9000:9000" in all_args

    def test_on_step_called_twice(self, tmp_path: Path) -> None:
        profile = _make_profile()
        steps: list[str] = []
        with patch(PATCH, return_value=""):
            run(profile, "docker", tmp_path, on_step=lambda n, d: steps.append(n))
        assert len(steps) == 2


# ── docker-compose ─────────────────────────────────────────────────────────────

class TestComposeRunner:
    def test_calls_compose_up(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "docker-compose", tmp_path)
        args = mock.call_args.args[0]
        assert "docker" in args
        assert "compose" in args
        assert "up" in args

    def test_compose_runs_detached(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "docker-compose", tmp_path)
        args = mock.call_args.args[0]
        assert "-d" in args


# ── kubernetes ─────────────────────────────────────────────────────────────────

class TestKubernetesRunner:
    def test_applies_manifests_and_waits(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "k8s").mkdir()
        with patch(PATCH, return_value="") as mock:
            run(profile, "kubernetes", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("apply" in c for c in calls)
        assert any("rollout" in c for c in calls)

    def test_on_step_called_twice(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "k8s").mkdir()
        steps: list[str] = []
        with patch(PATCH, return_value=""):
            run(profile, "kubernetes", tmp_path, on_step=lambda n, d: steps.append(n))
        assert len(steps) == 2


# ── helm ───────────────────────────────────────────────────────────────────────

class TestHelmRunner:
    def test_calls_helm_upgrade_install(self, tmp_path: Path) -> None:
        profile = _make_profile()
        helm_dir = tmp_path / "helm" / profile.project
        helm_dir.mkdir(parents=True)
        with patch(PATCH, return_value="") as mock:
            run(profile, "helm", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("helm" in c and "upgrade" in c and "--install" in c for c in calls)

    def test_waits_for_rollout(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "helm" / profile.project).mkdir(parents=True)
        with patch(PATCH, return_value="") as mock:
            run(profile, "helm", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("rollout" in c and "status" in c for c in calls)


# ── ec2 ────────────────────────────────────────────────────────────────────────

class TestEC2Runner:
    def test_raises_deploy_error_with_instructions(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with pytest.raises(DeployError, match="provision.sh"):
            run(profile, "ec2", tmp_path)


# ── ecs-fargate ────────────────────────────────────────────────────────────────

class TestECSRunner:
    def test_three_step_pipeline(self, tmp_path: Path) -> None:
        profile = _make_profile()
        steps: list[str] = []
        with patch(PATCH, return_value=""):
            run(profile, "ecs-fargate", tmp_path, on_step=lambda n, d: steps.append(n))
        assert len(steps) == 3

    def test_registers_task_definition(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "ecs-fargate", tmp_path)
        all_args = [arg for c in mock.call_args_list for arg in c.args[0]]
        assert "register-task-definition" in all_args


# ── lambda ─────────────────────────────────────────────────────────────────────

class TestLambdaRunner:
    def test_calls_sam_build_and_deploy(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "lambda", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("sam" in c and "build" in c for c in calls)
        assert any("sam" in c and "deploy" in c for c in calls)

    def test_sam_deploy_has_stack_name(self, tmp_path: Path) -> None:
        profile = _make_profile(project="lambdaapp")
        with patch(PATCH, return_value="") as mock:
            run(profile, "lambda", tmp_path)
        all_args = [arg for c in mock.call_args_list for arg in c.args[0]]
        assert "lambdaapp" in all_args

    def test_on_step_called_three_times(self, tmp_path: Path) -> None:
        profile = _make_profile()
        steps: list[str] = []
        with patch(PATCH, return_value=""):
            run(profile, "lambda", tmp_path, on_step=lambda n, d: steps.append(n))
        assert len(steps) == 3


# ── fly.io ─────────────────────────────────────────────────────────────────────

class TestFlyioRunner:
    def test_calls_flyctl_deploy(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "fly.toml").write_text("app = 'myapp'\n")
        with patch(PATCH, return_value="") as mock:
            run(profile, "fly.io", tmp_path)
        all_args = [arg for c in mock.call_args_list for arg in c.args[0]]
        assert "flyctl" in all_args
        assert "deploy" in all_args

    def test_passes_config_path(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "fly.toml").write_text("app = 'myapp'\n")
        with patch(PATCH, return_value="") as mock:
            run(profile, "fly.io", tmp_path)
        all_args = [arg for c in mock.call_args_list for arg in c.args[0]]
        assert "--config" in all_args


# ── railway ────────────────────────────────────────────────────────────────────

class TestRailwayRunner:
    def test_calls_railway_up(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "railway", tmp_path)
        args = mock.call_args.args[0]
        assert "railway" in args
        assert "up" in args

    def test_runs_detached(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "railway", tmp_path)
        args = mock.call_args.args[0]
        assert "--detach" in args


# ── cloud-run ──────────────────────────────────────────────────────────────────

class TestCloudRunRunner:
    def test_three_gcloud_calls(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "cloudbuild.yaml").write_text("steps: []\n")
        (tmp_path / "service.yaml").write_text("apiVersion: serving.knative.dev/v1\n")
        with patch(PATCH, return_value="") as mock:
            run(profile, "cloud-run", tmp_path)
        assert mock.call_count == 3

    def test_calls_gcloud_builds_submit(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "cloudbuild.yaml").write_text("")
        (tmp_path / "service.yaml").write_text("")
        with patch(PATCH, return_value="") as mock:
            run(profile, "cloud-run", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("builds" in c and "submit" in c for c in calls)

    def test_calls_gcloud_run_services_replace(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "cloudbuild.yaml").write_text("")
        (tmp_path / "service.yaml").write_text("")
        with patch(PATCH, return_value="") as mock:
            run(profile, "cloud-run", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("run" in c and "services" in c and "replace" in c for c in calls)


# ── azure-container ────────────────────────────────────────────────────────────

class TestAzureRunner:
    def test_three_step_pipeline(self, tmp_path: Path) -> None:
        profile = _make_profile()
        steps: list[str] = []
        with patch(PATCH, return_value=""):
            run(profile, "azure-container", tmp_path, on_step=lambda n, d: steps.append(n))
        assert len(steps) == 3

    def test_calls_az_acr_build(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "azure-container", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("az" in c and "acr" in c and "build" in c for c in calls)

    def test_calls_az_container_create(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with patch(PATCH, return_value="") as mock:
            run(profile, "azure-container", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("az" in c and "container" in c and "create" in c for c in calls)


# ── systemd ────────────────────────────────────────────────────────────────────

class TestSystemdRunner:
    def test_four_step_pipeline(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / f"{profile.project}.service").write_text("[Unit]\n")
        steps: list[str] = []
        with patch(PATCH, return_value=""):
            run(profile, "systemd", tmp_path, on_step=lambda n, d: steps.append(n))
        assert len(steps) == 4

    def test_copies_service_file(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        (tmp_path / "myapp.service").write_text("[Unit]\n")
        with patch(PATCH, return_value="") as mock:
            run(profile, "systemd", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("cp" in c for c in calls)

    def test_enables_and_starts_service(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        (tmp_path / "myapp.service").write_text("[Unit]\n")
        with patch(PATCH, return_value="") as mock:
            run(profile, "systemd", tmp_path)
        all_args = [arg for c in mock.call_args_list for arg in c.args[0]]
        assert "enable" in all_args
        assert "start" in all_args

    def test_runs_daemon_reload(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        (tmp_path / "myapp.service").write_text("[Unit]\n")
        with patch(PATCH, return_value="") as mock:
            run(profile, "systemd", tmp_path)
        all_args = [arg for c in mock.call_args_list for arg in c.args[0]]
        assert "daemon-reload" in all_args


# ── process ────────────────────────────────────────────────────────────────────

class TestProcessRunner:
    def test_executes_run_sh(self, tmp_path: Path) -> None:
        profile = _make_profile()
        (tmp_path / "run.sh").write_text("#!/bin/bash\necho hi\n")
        with patch(PATCH, return_value="") as mock:
            run(profile, "process", tmp_path)
        all_args = [arg for c in mock.call_args_list for arg in c.args[0]]
        assert any("run.sh" in a for a in all_args)

    def test_raises_if_run_sh_missing(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with pytest.raises(DeployError, match="run.sh not found"):
            run(profile, "process", tmp_path)

    def test_makes_run_sh_executable(self, tmp_path: Path) -> None:
        """On non-Windows platforms, chmod +x should be called before run.sh."""
        profile = _make_profile()
        (tmp_path / "run.sh").write_text("#!/bin/bash\necho hi\n")
        with patch(PATCH, return_value="") as mock, \
             patch("zonny_core.deploy.runner.sys") as mock_sys:
            mock_sys.platform = "linux"
            run(profile, "process", tmp_path)
        calls = [c.args[0] for c in mock.call_args_list]
        assert any("chmod" in c for c in calls)

    def test_two_step_pipeline(self, tmp_path: Path) -> None:
        """On non-Windows platforms, there should be exactly 2 steps."""
        profile = _make_profile()
        (tmp_path / "run.sh").write_text("#!/bin/bash\necho hi\n")
        steps: list[str] = []
        with patch(PATCH, return_value=""), \
             patch("zonny_core.deploy.runner.sys") as mock_sys:
            mock_sys.platform = "linux"
            run(profile, "process", tmp_path, on_step=lambda n, d: steps.append(n))
        assert len(steps) == 2
