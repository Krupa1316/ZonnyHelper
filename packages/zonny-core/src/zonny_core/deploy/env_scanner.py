"""Environment scanner — detect OS, installed tools, cloud context, and resources.

This is Phase 1 of the Universal Deployer (see DEPLOYER_ROADMAP.md).

``scan_env()`` returns an :class:`EnvProfile` that describes:
  - OS and CPU architecture
  - Which deployment tools are installed (docker, kubectl, flyctl, etc.)
  - Whether Docker daemon is actually running
  - Cloud context (AWS EC2, GCP, Azure, GitHub Actions, or local)
  - Current kubectl context (if applicable)
  - Cloud-specific context (AWS region, GCP project, Azure subscription)
  - System resources via psutil (optional — gracefully absent)
  - Whether running inside a CI environment

Together with :class:`~zonny_core.deploy.profile.DeployProfile` from
``scanner.py``, an `EnvProfile`` feeds the AI DeploymentAdvisor which powers
``zonny deploy auto``.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    import httpx
    _HTTPX = True
except ImportError:
    _HTTPX = False


# ── Constants ─────────────────────────────────────────────────────────────────

TOOLS = [
    "docker", "docker-compose", "kubectl", "helm",
    "flyctl", "railway", "gcloud", "aws", "az",
    "terraform", "heroku", "pulumi",
]

_IMDS_TIMEOUT = 1.0  # seconds — must not block on non-cloud machines

_EC2_URL   = "http://169.254.169.254/latest/meta-data/instance-id"
_GCP_URL   = "http://metadata.google.internal/computeMetadata/v1/project/project-id"
_AZURE_URL = "http://169.254.169.254/metadata/instance?api-version=2021-02-01"


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class EnvProfile:
    """A snapshot of the deployment environment.

    All fields are populated by :func:`scan_env`. Fields that require an
    outside network call (cloud context) or optional deps (psutil) fall back to
    safe defaults rather than raising.
    """

    os: str                            # "linux" | "macos" | "windows"
    arch: str                          # "x86_64" | "arm64"
    cloud_context: str                 # "aws-ec2" | "gcp-gce" | "azure-vm"
                                       # | "github-actions" | "docker-container" | "local"
    tools: dict[str, bool] = field(default_factory=dict)
    docker_running: bool = False       # docker daemon is alive
    k8s_context: str | None = None     # current kubectl context name
    aws_region: str | None = None      # from IMDS or AWS_DEFAULT_REGION env var
    gcp_project: str | None = None     # from IMDS or GCLOUD_PROJECT env var
    azure_subscription: str | None = None
    ram_gb: float = 0.0                # total system RAM in GB
    cpu_cores: int = 0
    disk_free_gb: float = 0.0          # free disk on cwd filesystem
    ci: bool = False                   # running inside a CI system?
    ci_provider: str | None = None     # "github-actions" | "gitlab-ci" | "circleci" | None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ── Public API ────────────────────────────────────────────────────────────────

def scan_env() -> EnvProfile:
    """Detect the current deployment environment and return an :class:`EnvProfile`.

    All detection is non-blocking:
    - IMDS HTTP calls use a 1-second timeout.
    - subprocess calls use short timeouts and swallow errors.
    - psutil is optional; if absent, resource fields stay at 0.
    """
    os_name = _detect_os()
    arch = _detect_arch()
    ci, ci_provider = _detect_ci()

    # Fast-path: if we know it's GH Actions or similar, skip cloud IMDS
    if ci_provider == "github-actions":
        cloud_context = "github-actions"
        aws_region = os.environ.get("AWS_DEFAULT_REGION")
        gcp_project = os.environ.get("GCLOUD_PROJECT") or os.environ.get("CLOUDSDK_CORE_PROJECT")
        azure_subscription = None
    else:
        cloud_context, aws_region, gcp_project, azure_subscription = _detect_cloud()

    tools = _detect_tools()
    docker_running = _check_docker_running() if tools.get("docker") else False
    k8s_context = _detect_k8s_context() if tools.get("kubectl") else None
    ram_gb, cpu_cores, disk_free_gb = _detect_resources()

    return EnvProfile(
        os=os_name,
        arch=arch,
        cloud_context=cloud_context,
        tools=tools,
        docker_running=docker_running,
        k8s_context=k8s_context,
        aws_region=aws_region,
        gcp_project=gcp_project,
        azure_subscription=azure_subscription,
        ram_gb=ram_gb,
        cpu_cores=cpu_cores,
        disk_free_gb=disk_free_gb,
        ci=ci,
        ci_provider=ci_provider,
    )


# ── Detection helpers ─────────────────────────────────────────────────────────

def _detect_os() -> str:
    """Return normalised OS name: 'linux' | 'macos' | 'windows'."""
    sys = platform.system().lower()
    if sys == "darwin":
        return "macos"
    if sys == "windows":
        return "windows"
    return "linux"


def _detect_arch() -> str:
    """Return normalised CPU architecture: 'x86_64' | 'arm64'."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "x86_64"


def _detect_ci() -> tuple[bool, str | None]:
    """Return (is_ci, provider_name)."""
    if os.environ.get("GITHUB_ACTIONS"):
        return True, "github-actions"
    if os.environ.get("GITLAB_CI"):
        return True, "gitlab-ci"
    if os.environ.get("CIRCLECI"):
        return True, "circleci"
    if os.environ.get("CI") or os.environ.get("CONTINUOUS_INTEGRATION"):
        return True, None
    return False, None


def _detect_tools() -> dict[str, bool]:
    """Check which deployment tools are on PATH using shutil.which()."""
    return {tool: shutil.which(tool) is not None for tool in TOOLS}


def _check_docker_running() -> bool:
    """Return True if the Docker daemon responds to 'docker info'."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=3,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _detect_k8s_context() -> str | None:
    """Return the current kubectl context name, or None if unavailable."""
    try:
        result = subprocess.run(
            ["kubectl", "config", "current-context"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            ctx = result.stdout.strip()
            return ctx if ctx else None
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _detect_cloud() -> tuple[str, str | None, str | None, str | None]:
    """Probe cloud IMDS endpoints; return (cloud_context, aws_region, gcp_project, azure_sub).

    Uses httpx if available, falls back to urllib. All probes are fire-and-forget
    with a 1-second connect timeout to avoid blocking on non-cloud machines.
    """
    # Check in-container hint first (no network needed)
    if os.path.exists("/.dockerenv"):
        return "docker-container", None, None, None

    aws_region, gcp_project, azure_sub = None, None, None

    # --- AWS EC2 ---
    aws_region = os.environ.get("AWS_DEFAULT_REGION")
    if _probe_url(_EC2_URL):
        # Try to get region from IMDS
        region = _fetch_text(
            "http://169.254.169.254/latest/meta-data/placement/region",
            timeout=_IMDS_TIMEOUT,
        )
        if region:
            aws_region = region
        elif not aws_region:
            aws_region = _infer_aws_region_from_az()
        return "aws-ec2", aws_region, None, None

    # --- GCP ---
    gcp_project = (
        os.environ.get("GCLOUD_PROJECT")
        or os.environ.get("CLOUDSDK_CORE_PROJECT")
    )
    if _probe_url(_GCP_URL, headers={"Metadata-Flavor": "Google"}):
        project = _fetch_text(
            _GCP_URL,
            headers={"Metadata-Flavor": "Google"},
            timeout=_IMDS_TIMEOUT,
        )
        if project:
            gcp_project = project
        return "gcp-gce", None, gcp_project, None

    # --- Azure ---
    if _probe_url(_AZURE_URL, headers={"Metadata": "true"}):
        try:
            text = _fetch_text(
                _AZURE_URL,
                headers={"Metadata": "true"},
                timeout=_IMDS_TIMEOUT,
            )
            if text:
                data = json.loads(text)
                azure_sub = (
                    data.get("compute", {}).get("subscriptionId")
                )
        except Exception:  # noqa: BLE001
            pass
        return "azure-vm", None, None, azure_sub

    return "local", aws_region, gcp_project, None


def _probe_url(url: str, headers: dict[str, str] | None = None, timeout: float = _IMDS_TIMEOUT) -> bool:
    """Return True if *url* responds within *timeout* seconds."""
    try:
        if _HTTPX:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(url, headers=headers or {})
                return r.status_code < 500
        else:
            import urllib.request  # noqa: PLC0415
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout):  # noqa: S310
                return True
    except Exception:  # noqa: BLE001
        return False


def _fetch_text(url: str, headers: dict[str, str] | None = None, timeout: float = _IMDS_TIMEOUT) -> str | None:
    """Fetch plain text from *url*; return None on any error."""
    try:
        if _HTTPX:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(url, headers=headers or {})
                return r.text.strip() if r.status_code == 200 else None
        else:
            import urllib.request  # noqa: PLC0415
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read().decode().strip()
    except Exception:  # noqa: BLE001
        return None


def _infer_aws_region_from_az() -> str | None:
    """Try to get region from availability-zone IMDS endpoint."""
    az = _fetch_text("http://169.254.169.254/latest/meta-data/placement/availability-zone")
    if az and len(az) > 2:
        return az[:-1]  # strip trailing letter, e.g. "us-east-1a" → "us-east-1"
    return None


def _detect_resources() -> tuple[float, int, float]:
    """Return (ram_gb, cpu_cores, disk_free_gb) using psutil if available."""
    if not _PSUTIL:
        return 0.0, 0, 0.0
    try:
        ram_gb = psutil.virtual_memory().total / 1e9
        cpu_cores = psutil.cpu_count(logical=True) or 0
        disk_free_gb = psutil.disk_usage(os.getcwd()).free / 1e9
        return round(ram_gb, 2), cpu_cores, round(disk_free_gb, 2)
    except Exception:  # noqa: BLE001
        return 0.0, 0, 0.0
