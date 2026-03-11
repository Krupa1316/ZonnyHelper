"""Deploy runner — executes a deployment and streams live logs.

`zonny deploy run` delegates to the underlying tool (docker, docker-compose,
kubectl, aws cli, flyctl, railway, gcloud, az, helm) and streams its
stdout/stderr to the terminal in real time. On failure it surfaces the
error context so `zonny-ai` can diagnose it.

Supported targets:
  docker, docker-compose, kubernetes, helm,
  ec2, ecs-fargate, lambda,
  fly.io, railway, cloud-run, azure-container,
  systemd, process
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

from zonny_core.deploy.profile import DeployProfile


class DeployError(Exception):
    """Raised when a deployment step fails."""

    def __init__(self, message: str, log: str) -> None:
        super().__init__(message)
        self.log = log  # captured output for AI diagnosis


def run(
    profile: DeployProfile,
    target: str,
    deploy_dir: Path,
    on_step: Callable[[str, str], None] | None = None,
) -> None:
    """Execute the deployment for *target*.

    Parameters
    ----------
    profile:
        The DeployProfile produced by ``scan()``.
    target:
        The deployment target (e.g. "docker-compose").
    deploy_dir:
        Directory containing the generated config files.
    on_step:
        Optional callback ``(step_name, description) -> None`` called before
        each step so the caller can show progress.
    """
    runners = {
        "docker":           _run_docker,
        "docker-compose":   _run_compose,
        "kubernetes":       _run_kubernetes,
        "helm":             _run_helm,
        "ec2":              _run_ec2,
        "ecs-fargate":      _run_ecs,
        "lambda":           _run_lambda,
        "fly.io":           _run_flyio,
        "railway":          _run_railway,
        "cloud-run":        _run_cloudrun,
        "azure-container":  _run_azure,
        "systemd":          _run_systemd,
        "process":          _run_process,
    }
    fn = runners.get(target)
    if fn is None:
        raise DeployError(f"No runner for target '{target}'.", log="")
    fn(profile, deploy_dir, on_step or (lambda *a: None))


# ── Shared subprocess helper ──────────────────────────────────────────────────

def _run_streaming(cmd: list[str], cwd: Path) -> str:
    """Run *cmd* in *cwd*, streaming output to stdout and capturing it."""
    captured: list[str] = []
    with subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            captured.append(line)
        proc.wait()
        if proc.returncode != 0:
            raise DeployError(
                f"Command failed: {' '.join(cmd)}",
                log="".join(captured),
            )
    return "".join(captured)


# ── Target runners ─────────────────────────────────────────────────────────────

def _run_docker(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/2", "Building Docker image…")
    _run_streaming(["docker", "build", "-t", p.project, "."], d)
    step("2/2", f"Running container on port {p.port}…")
    _run_streaming(
        ["docker", "run", "-d", "--name", p.project, "-p", f"{p.port}:{p.port}", p.project],
        d,
    )


def _run_compose(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/1", "Starting docker compose stack…")
    _run_streaming(["docker", "compose", "up", "--build", "-d"], d)


def _run_kubernetes(p: DeployProfile, d: Path, step: Callable) -> None:
    k8s = d / "k8s"
    step("1/2", "Applying Kubernetes manifests…")
    _run_streaming(["kubectl", "apply", "-f", str(k8s)], d)
    step("2/2", f"Waiting for rollout of deployment/{p.project}…")
    _run_streaming(["kubectl", "rollout", "status", f"deployment/{p.project}"], d)


def _run_ec2(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/1", "EC2 provisioning requires running provision.sh on your target host.")
    raise DeployError(
        "EC2 deployment requires manual execution of provision.sh on the target host.\n"
        "Copy provision.sh and app.service to your EC2 instance and run:\n"
        "  chmod +x provision.sh && sudo ./provision.sh",
        log="",
    )


def _run_ecs(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/3", "Building and pushing Docker image to ECR…")
    _run_streaming(["docker", "build", "-t", p.project, "."], d)
    step("2/3", "Registering ECS task definition…")
    _run_streaming(
        ["aws", "ecs", "register-task-definition", "--cli-input-json",
         f"file://{d}/task-definition.json"],
        d,
    )
    step("3/3", "Creating/updating ECS service…")
    _run_streaming(
        ["aws", "ecs", "create-service", "--cli-input-json",
         f"file://{d}/ecs-service.json"],
        d,
    )


def _run_lambda(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/3", "Building Lambda package with SAM…")
    _run_streaming(["sam", "build"], d)
    step("2/3", "Deploying to AWS Lambda via SAM…")
    _run_streaming(
        ["sam", "deploy",
         "--stack-name", p.project,
         "--capabilities", "CAPABILITY_IAM",
         "--resolve-s3",
         "--no-confirm-changeset"],
        d,
    )
    step("3/3", f"Lambda function '{p.project}' deployed.")


def _run_helm(p: DeployProfile, d: Path, step: Callable) -> None:
    chart_dir = d / "helm" / p.project
    step("1/2", f"Installing/upgrading Helm release '{p.project}'…")
    _run_streaming(
        ["helm", "upgrade", "--install", p.project, str(chart_dir),
         "--wait", "--timeout", "5m0s"],
        d,
    )
    step("2/2", f"Waiting for rollout of deployment/{p.project}…")
    _run_streaming(
        ["kubectl", "rollout", "status", f"deployment/{p.project}"],
        d,
    )


def _run_flyio(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/2", "Deploying to Fly.io…")
    _run_streaming(
        ["flyctl", "deploy", "--config", str(d / "fly.toml"), "--remote-only"],
        d,
    )
    step("2/2", "Fly.io deployment complete.")


def _run_railway(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/1", "Deploying to Railway…")
    _run_streaming(["railway", "up", "--detach"], d)


def _run_cloudrun(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/3", "Submitting build to Google Cloud Build…")
    _run_streaming(
        ["gcloud", "builds", "submit",
         "--config", str(d / "cloudbuild.yaml"), "."],
        d,
    )
    step("2/3", "Deploying to Cloud Run…")
    _run_streaming(
        ["gcloud", "run", "services", "replace",
         str(d / "service.yaml"),
         "--region", "us-central1",
         "--platform", "managed"],
        d,
    )
    step("3/3", "Making Cloud Run service publicly accessible…")
    _run_streaming(
        ["gcloud", "run", "services", "add-iam-policy-binding", p.project,
         "--region", "us-central1",
         "--member", "allUsers",
         "--role", "roles/run.invoker"],
        d,
    )


def _run_azure(p: DeployProfile, d: Path, step: Callable) -> None:
    step("1/3", "Building and pushing image to Azure Container Registry…")
    _run_streaming(
        ["az", "acr", "build",
         "--registry", "$ACR_NAME",
         "--image", f"{p.project}:latest", "."],
        d,
    )
    step("2/3", "Creating Azure Container Instance…")
    _run_streaming(
        ["az", "container", "create",
         "--resource-group", "$RESOURCE_GROUP",
         "--name", p.project,
         "--image", f"$ACR_NAME.azurecr.io/{p.project}:latest",
         "--ports", str(p.port),
         "--dns-name-label", p.project,
         "--memory", str(round(int(p.estimated_memory.replace("MB", "").replace("GB", "000")) / 1024, 1)),
         "--cpu", "1"],
        d,
    )
    step("3/3", f"Azure Container Instance '{p.project}' deployed.")


def _run_systemd(p: DeployProfile, d: Path, step: Callable) -> None:
    service_src = d / f"{p.project}.service"
    service_dst = f"/etc/systemd/system/{p.project}.service"
    step("1/4", f"Copying {p.project}.service to {service_dst}…")
    _run_streaming(["sudo", "cp", str(service_src), service_dst], d)
    step("2/4", "Reloading systemd daemon…")
    _run_streaming(["sudo", "systemctl", "daemon-reload"], d)
    step("3/4", f"Enabling {p.project} service…")
    _run_streaming(["sudo", "systemctl", "enable", p.project], d)
    step("4/4", f"Starting {p.project} service…")
    _run_streaming(["sudo", "systemctl", "start", p.project], d)


def _run_process(p: DeployProfile, d: Path, step: Callable) -> None:
    run_sh = d / "run.sh"
    run_bat = d / "run.bat"
    # Project root is two levels up: .zonny/generated → .zonny → project root
    project_root = d.parent.parent if d.parent.name == ".zonny" else Path.cwd()

    if not run_sh.exists():
        raise DeployError(
            "run.sh not found. Run 'zonny deploy generate --target process' first.",
            log="",
        )
    if sys.platform == "win32":
        # Windows: skip chmod, find bash (Git for Windows / WSL) or use run.bat
        bash = _find_windows_bash()
        if bash:
            step("1/2", f"Starting {p.project} via bash run.sh…")
            _run_streaming([bash, str(run_sh)], project_root)
        elif run_bat.exists():
            step("1/2", f"Starting {p.project} via run.bat…")
            _run_streaming([str(run_bat)], project_root)
        else:
            # Fallback: run build + start commands directly from project root
            if p.build_cmd:
                step("1/2", f"Installing dependencies: {p.build_cmd}…")
                _run_streaming(p.build_cmd.split(), project_root)
            step("2/2", f"Starting {p.project}: {p.start_cmd}…")
            _run_streaming(p.start_cmd.split(), project_root)
    else:
        step("1/2", "Making run.sh executable…")
        _run_streaming(["chmod", "+x", str(run_sh)], project_root)
        step("2/2", f"Starting {p.project} via run.sh…")
        _run_streaming([str(run_sh)], project_root)


def _find_windows_bash() -> str | None:
    """Return the path to bash.exe on Windows, or None if not found."""
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Windows\System32\bash.exe",  # WSL bash
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    # Try $PATH
    import shutil
    return shutil.which("bash")
