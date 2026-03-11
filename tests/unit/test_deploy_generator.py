"""Unit tests for the deploy generator (generator.py).

Tests verify that generated files contain the expected content for each target.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from zonny_core.deploy.generator import generate
from zonny_core.deploy.profile import DBDependency, DeployProfile


def _make_profile(**overrides) -> DeployProfile:
    defaults = dict(
        project="testapp",
        language="python",
        runtime="3.11",
        framework="fastapi",
        entry_point="main.py",
        port=8000,
        build_cmd="pip install -r requirements.txt",
        start_cmd="uvicorn main:app --host 0.0.0.0 --port 8000",
        databases=[],
        env_vars=["SECRET_KEY", "DATABASE_URL"],
        has_static=False,
        estimated_memory="512MB",
        deploy_targets=["docker", "docker-compose", "kubernetes"],
    )
    defaults.update(overrides)
    return DeployProfile(**defaults)


class TestDockerGenerator:
    def test_generates_dockerfile(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "docker", tmp_path)
        paths = [f.name for f in files]
        assert "Dockerfile" in paths
        assert ".dockerignore" in paths

    def test_dockerfile_has_correct_base_image(self, tmp_path: Path) -> None:
        profile = _make_profile(language="python", runtime="3.11")
        generate(profile, "docker", tmp_path)
        content = (tmp_path / "Dockerfile").read_text()
        assert "python:3.11-slim" in content

    def test_dockerfile_has_expose(self, tmp_path: Path) -> None:
        profile = _make_profile(port=9000)
        generate(profile, "docker", tmp_path)
        content = (tmp_path / "Dockerfile").read_text()
        assert "EXPOSE 9000" in content

    def test_dockerfile_has_healthcheck(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "docker", tmp_path)
        content = (tmp_path / "Dockerfile").read_text()
        assert "HEALTHCHECK" in content

    def test_dockerfile_non_root_user(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "docker", tmp_path)
        content = (tmp_path / "Dockerfile").read_text()
        assert "appuser" in content

    def test_node_dockerfile_uses_node_image(self, tmp_path: Path) -> None:
        profile = _make_profile(language="node", runtime="20", framework="express",
                                entry_point="index.js",
                                build_cmd="npm install",
                                start_cmd="node index.js")
        generate(profile, "docker", tmp_path)
        content = (tmp_path / "Dockerfile").read_text()
        assert "node:20-alpine" in content


class TestDockerComposeGenerator:
    def test_generates_compose_file(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "docker-compose", tmp_path)
        assert any(f.name == "docker-compose.yml" for f in files)

    def test_compose_has_app_service(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "docker-compose", tmp_path)
        content = (tmp_path / "docker-compose.yml").read_text()
        assert "app:" in content

    def test_compose_includes_postgres_when_db_detected(self, tmp_path: Path) -> None:
        profile = _make_profile(databases=[DBDependency(type="postgresql", orm="sqlalchemy")])
        generate(profile, "docker-compose", tmp_path)
        content = (tmp_path / "docker-compose.yml").read_text()
        assert "postgres:" in content.lower() or "db:" in content

    def test_compose_includes_nginx_when_static(self, tmp_path: Path) -> None:
        profile = _make_profile(has_static=True)
        generate(profile, "docker-compose", tmp_path)
        content = (tmp_path / "docker-compose.yml").read_text()
        assert "nginx" in content


class TestKubernetesGenerator:
    def test_generates_k8s_manifests(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "kubernetes", tmp_path)
        names = [f.name for f in files]
        assert "deployment.yaml" in names
        assert "service.yaml" in names
        assert "configmap.yaml" in names
        assert "ingress.yaml" in names

    def test_deployment_has_resource_limits(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "kubernetes", tmp_path)
        content = (tmp_path / "k8s" / "deployment.yaml").read_text()
        assert "limits:" in content
        assert "requests:" in content

    def test_deployment_has_probes(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "kubernetes", tmp_path)
        content = (tmp_path / "k8s" / "deployment.yaml").read_text()
        assert "livenessProbe" in content
        assert "readinessProbe" in content


class TestECSGenerator:
    def test_generates_ecs_files(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "ecs-fargate", tmp_path)
        names = [f.name for f in files]
        assert "task-definition.json" in names
        assert "ecs-service.json" in names

    def test_task_def_has_fargate(self, tmp_path: Path) -> None:
        import json
        profile = _make_profile()
        generate(profile, "ecs-fargate", tmp_path)
        td = json.loads((tmp_path / "task-definition.json").read_text())
        assert "FARGATE" in td.get("requiresCompatibilities", [])

    def test_task_def_has_cloudwatch_logging(self, tmp_path: Path) -> None:
        import json
        profile = _make_profile()
        generate(profile, "ecs-fargate", tmp_path)
        td = json.loads((tmp_path / "task-definition.json").read_text())
        containers = td.get("containerDefinitions", [])
        assert len(containers) > 0
        assert containers[0].get("logConfiguration", {}).get("logDriver") == "awslogs"


class TestLambdaGenerator:
    def test_generates_lambda_files(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "lambda", tmp_path)
        names = [f.name for f in files]
        assert "handler.py" in names
        assert "template.yaml" in names

    def test_sam_template_has_serverless_transform(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "lambda", tmp_path)
        content = (tmp_path / "template.yaml").read_text()
        assert "AWS::Serverless" in content

    def test_invalid_target_raises_value_error(self, tmp_path: Path) -> None:
        profile = _make_profile()
        with pytest.raises(ValueError, match="Unknown deploy target"):
            generate(profile, "invalid-target", tmp_path)


class TestFlyioGenerator:
    def test_generates_fly_toml(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "fly.io", tmp_path)
        assert any(f.name == "fly.toml" for f in files)

    def test_fly_toml_has_app_name(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapi")
        generate(profile, "fly.io", tmp_path)
        content = (tmp_path / "fly.toml").read_text()
        assert 'app = "myapi"' in content

    def test_fly_toml_has_internal_port(self, tmp_path: Path) -> None:
        profile = _make_profile(port=9000)
        generate(profile, "fly.io", tmp_path)
        content = (tmp_path / "fly.toml").read_text()
        assert "internal_port = 9000" in content

    def test_fly_toml_has_vm_section(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "fly.io", tmp_path)
        content = (tmp_path / "fly.toml").read_text()
        assert "[[vm]]" in content
        assert "cpu_kind" in content

    def test_fly_toml_has_env_vars(self, tmp_path: Path) -> None:
        profile = _make_profile(env_vars=["DATABASE_URL", "SECRET_KEY"])
        generate(profile, "fly.io", tmp_path)
        content = (tmp_path / "fly.toml").read_text()
        assert "[env]" in content
        assert "DATABASE_URL" in content


class TestRailwayGenerator:
    def test_generates_railway_json(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "railway", tmp_path)
        names = [f.name for f in files]
        assert "railway.json" in names
        assert "nixpacks.toml" in names

    def test_railway_json_schema(self, tmp_path: Path) -> None:
        import json as _json
        profile = _make_profile()
        generate(profile, "railway", tmp_path)
        data = _json.loads((tmp_path / "railway.json").read_text())
        assert data.get("$schema") == "https://railway.app/railway.schema.json"

    def test_railway_json_has_start_command(self, tmp_path: Path) -> None:
        import json as _json
        profile = _make_profile(start_cmd="uvicorn main:app --host 0.0.0.0 --port 8000")
        generate(profile, "railway", tmp_path)
        data = _json.loads((tmp_path / "railway.json").read_text())
        assert data["deploy"]["startCommand"] == "uvicorn main:app --host 0.0.0.0 --port 8000"

    def test_nixpacks_toml_has_start_cmd(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "railway", tmp_path)
        content = (tmp_path / "nixpacks.toml").read_text()
        assert "[start]" in content
        assert "cmd" in content


class TestCloudRunGenerator:
    def test_generates_service_yaml_and_cloudbuild(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "cloud-run", tmp_path)
        names = [f.name for f in files]
        assert "service.yaml" in names
        assert "cloudbuild.yaml" in names

    def test_service_yaml_is_knative(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "cloud-run", tmp_path)
        content = (tmp_path / "service.yaml").read_text()
        assert "serving.knative.dev/v1" in content

    def test_service_yaml_has_project_name(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myservice")
        generate(profile, "cloud-run", tmp_path)
        content = (tmp_path / "service.yaml").read_text()
        assert "myservice" in content

    def test_service_yaml_has_container_port(self, tmp_path: Path) -> None:
        profile = _make_profile(port=8080)
        generate(profile, "cloud-run", tmp_path)
        content = (tmp_path / "service.yaml").read_text()
        assert "containerPort: 8080" in content

    def test_service_yaml_memory_in_mebibytes(self, tmp_path: Path) -> None:
        profile = _make_profile(estimated_memory="512MB")
        generate(profile, "cloud-run", tmp_path)
        content = (tmp_path / "service.yaml").read_text()
        assert "512Mi" in content

    def test_cloudbuild_has_gcloud_run_deploy(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "cloud-run", tmp_path)
        content = (tmp_path / "cloudbuild.yaml").read_text()
        assert "gcloud" in content
        assert "run" in content


class TestSystemdGenerator:
    def test_generates_service_file_and_install_script(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        files = generate(profile, "systemd", tmp_path)
        names = [f.name for f in files]
        assert "myapp.service" in names
        assert "install-service.sh" in names

    def test_service_file_has_unit_section(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        generate(profile, "systemd", tmp_path)
        content = (tmp_path / "myapp.service").read_text()
        assert "[Unit]" in content
        assert "[Service]" in content
        assert "[Install]" in content

    def test_service_file_has_restart_policy(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        generate(profile, "systemd", tmp_path)
        content = (tmp_path / "myapp.service").read_text()
        assert "Restart=" in content

    def test_service_file_has_security_hardening(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        generate(profile, "systemd", tmp_path)
        content = (tmp_path / "myapp.service").read_text()
        assert "NoNewPrivileges=true" in content
        assert "PrivateTmp=true" in content

    def test_python_exec_start_uses_venv(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp", language="python")
        generate(profile, "systemd", tmp_path)
        content = (tmp_path / "myapp.service").read_text()
        assert ".venv" in content

    def test_install_script_has_systemctl(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        generate(profile, "systemd", tmp_path)
        content = (tmp_path / "install-service.sh").read_text()
        assert "systemctl" in content
        assert "daemon-reload" in content


class TestProcessGenerator:
    def test_generates_run_sh_and_env_example(self, tmp_path: Path) -> None:
        profile = _make_profile()
        files = generate(profile, "process", tmp_path)
        names = [f.name for f in files]
        assert "run.sh" in names
        assert ".env.example" in names

    def test_run_sh_has_start_cmd(self, tmp_path: Path) -> None:
        profile = _make_profile(start_cmd="uvicorn main:app --host 0.0.0.0 --port 8000")
        generate(profile, "process", tmp_path)
        content = (tmp_path / "run.sh").read_text()
        assert "uvicorn main:app" in content

    def test_run_sh_loads_dotenv(self, tmp_path: Path) -> None:
        profile = _make_profile()
        generate(profile, "process", tmp_path)
        content = (tmp_path / "run.sh").read_text()
        assert "source .env" in content

    def test_python_run_sh_creates_venv(self, tmp_path: Path) -> None:
        profile = _make_profile(language="python")
        generate(profile, "process", tmp_path)
        content = (tmp_path / "run.sh").read_text()
        assert ".venv" in content

    def test_env_example_has_all_env_vars(self, tmp_path: Path) -> None:
        profile = _make_profile(env_vars=["DATABASE_URL", "SECRET_KEY", "REDIS_URL"])
        generate(profile, "process", tmp_path)
        content = (tmp_path / ".env.example").read_text()
        assert "DATABASE_URL=" in content
        assert "SECRET_KEY=" in content
        assert "REDIS_URL=" in content


class TestHelmGenerator:
    def test_generates_helm_chart_structure(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        files = generate(profile, "helm", tmp_path)
        names = [f.name for f in files]
        assert "Chart.yaml" in names
        assert "values.yaml" in names
        assert "_helpers.tpl" in names
        assert "deployment.yaml" in names
        assert "service.yaml" in names
        assert "ingress.yaml" in names

    def test_chart_yaml_has_app_name(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        generate(profile, "helm", tmp_path)
        content = (tmp_path / "helm" / "myapp" / "Chart.yaml").read_text()
        assert "name: myapp" in content
        assert "apiVersion: v2" in content

    def test_values_yaml_has_replica_count(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        generate(profile, "helm", tmp_path)
        content = (tmp_path / "helm" / "myapp" / "values.yaml").read_text()
        assert "replicaCount:" in content

    def test_values_yaml_memory_in_mebibytes(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp", estimated_memory="256MB")
        generate(profile, "helm", tmp_path)
        content = (tmp_path / "helm" / "myapp" / "values.yaml").read_text()
        assert "256Mi" in content

    def test_values_yaml_has_env_vars(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp", env_vars=["DATABASE_URL"])
        generate(profile, "helm", tmp_path)
        content = (tmp_path / "helm" / "myapp" / "values.yaml").read_text()
        assert "DATABASE_URL" in content

    def test_deployment_template_has_helm_template_directives(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        generate(profile, "helm", tmp_path)
        content = (tmp_path / "helm" / "myapp" / "templates" / "deployment.yaml").read_text()
        assert ".Values.replicaCount" in content
        assert ".Values.image.repository" in content

    def test_ingress_template_is_conditional(self, tmp_path: Path) -> None:
        profile = _make_profile(project="myapp")
        generate(profile, "helm", tmp_path)
        content = (tmp_path / "helm" / "myapp" / "templates" / "ingress.yaml").read_text()
        assert ".Values.ingress.enabled" in content

    def test_new_language_docker_images(self, tmp_path: Path) -> None:
        """Verify _generate_docker picks correct base images for Phase 3 languages."""
        for lang, runtime, expected in [
            ("rust",       "1.78",    "rust:1.78-slim"),
            ("php",        "8.2",     "php:8.2-fpm-alpine"),
            ("dotnet",     "8.0",     "mcr.microsoft.com/dotnet/aspnet:8.0"),
            ("dart",       "3.3",     "dart:3.3"),
            ("typescript", "20",      "node:20-alpine"),
            ("static",     "nginx",   "nginx:alpine"),
        ]:
            p = _make_profile(language=lang, runtime=runtime,
                              build_cmd="echo build", start_cmd="echo start")
            generate(p, "docker", tmp_path)
            content = (tmp_path / "Dockerfile").read_text()
            assert expected in content, f"{lang}: expected '{expected}' in Dockerfile"
