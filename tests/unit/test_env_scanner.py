"""Unit tests for zonny_core.deploy.env_scanner (Phase 1 — Universal Deployer).

All network I/O, subprocess calls, and psutil are mocked so tests run
hermetically — no Docker daemon, no cloud, no external network needed.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from zonny_core.deploy.env_scanner import (
    EnvProfile,
    _check_docker_running,
    _detect_arch,
    _detect_ci,
    _detect_cloud,
    _detect_k8s_context,
    _detect_os,
    _detect_resources,
    _detect_tools,
    _infer_aws_region_from_az,
    scan_env,
)


# ── _detect_os ────────────────────────────────────────────────────────────────

class TestDetectOs:
    def test_linux(self):
        with patch("platform.system", return_value="Linux"):
            assert _detect_os() == "linux"

    def test_macos(self):
        with patch("platform.system", return_value="Darwin"):
            assert _detect_os() == "macos"

    def test_windows(self):
        with patch("platform.system", return_value="Windows"):
            assert _detect_os() == "windows"

    def test_unknown_falls_back_to_linux(self):
        with patch("platform.system", return_value="FreeBSD"):
            assert _detect_os() == "linux"


# ── _detect_arch ──────────────────────────────────────────────────────────────

class TestDetectArch:
    def test_x86_64(self):
        with patch("platform.machine", return_value="x86_64"):
            assert _detect_arch() == "x86_64"

    def test_amd64_maps_to_x86_64(self):
        with patch("platform.machine", return_value="AMD64"):
            assert _detect_arch() == "x86_64"

    def test_arm64(self):
        with patch("platform.machine", return_value="arm64"):
            assert _detect_arch() == "arm64"

    def test_aarch64_maps_to_arm64(self):
        with patch("platform.machine", return_value="aarch64"):
            assert _detect_arch() == "arm64"


# ── _detect_ci ────────────────────────────────────────────────────────────────

class TestDetectCi:
    def test_no_ci(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("GITLAB_CI", raising=False)
        monkeypatch.delenv("CIRCLECI", raising=False)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("CONTINUOUS_INTEGRATION", raising=False)
        ci, provider = _detect_ci()
        assert ci is False
        assert provider is None

    def test_github_actions(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.delenv("GITLAB_CI", raising=False)
        monkeypatch.delenv("CIRCLECI", raising=False)
        ci, provider = _detect_ci()
        assert ci is True
        assert provider == "github-actions"

    def test_gitlab_ci(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("GITLAB_CI", "true")
        ci, provider = _detect_ci()
        assert ci is True
        assert provider == "gitlab-ci"

    def test_circleci(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("GITLAB_CI", raising=False)
        monkeypatch.setenv("CIRCLECI", "true")
        ci, provider = _detect_ci()
        assert ci is True
        assert provider == "circleci"

    def test_generic_ci(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("GITLAB_CI", raising=False)
        monkeypatch.delenv("CIRCLECI", raising=False)
        monkeypatch.setenv("CI", "true")
        ci, provider = _detect_ci()
        assert ci is True
        assert provider is None


# ── _detect_tools ─────────────────────────────────────────────────────────────

class TestDetectTools:
    def test_all_missing(self):
        with patch("shutil.which", return_value=None):
            tools = _detect_tools()
        assert all(v is False for v in tools.values())
        assert "docker" in tools

    def test_docker_present(self):
        def _which(name):
            return "/usr/bin/docker" if name == "docker" else None

        with patch("shutil.which", side_effect=_which):
            tools = _detect_tools()

        assert tools["docker"] is True
        assert tools["kubectl"] is False

    def test_all_present(self):
        with patch("shutil.which", return_value="/usr/bin/tool"):
            tools = _detect_tools()
        assert all(v is True for v in tools.values())


# ── _check_docker_running ─────────────────────────────────────────────────────

class TestCheckDockerRunning:
    def test_daemon_running(self):
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            assert _check_docker_running() is True

    def test_daemon_not_running(self):
        mock_result = MagicMock(returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            assert _check_docker_running() is False

    def test_docker_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _check_docker_running() is False

    def test_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=3)):
            assert _check_docker_running() is False


# ── _detect_k8s_context ───────────────────────────────────────────────────────

class TestDetectK8sContext:
    def test_context_found(self):
        mock_result = MagicMock(returncode=0, stdout="my-cluster\n")
        with patch("subprocess.run", return_value=mock_result):
            assert _detect_k8s_context() == "my-cluster"

    def test_no_context(self):
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            assert _detect_k8s_context() is None

    def test_empty_output(self):
        mock_result = MagicMock(returncode=0, stdout="  \n")
        with patch("subprocess.run", return_value=mock_result):
            assert _detect_k8s_context() is None

    def test_kubectl_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _detect_k8s_context() is None

    def test_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="kubectl", timeout=5)):
            assert _detect_k8s_context() is None


# ── _detect_cloud ─────────────────────────────────────────────────────────────

class TestDetectCloud:
    def test_local_no_imds(self, monkeypatch, tmp_path):
        # Remove /.dockerenv, env vars that would trigger cloud
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
        monkeypatch.delenv("CLOUDSDK_CORE_PROJECT", raising=False)
        with patch("os.path.exists", return_value=False), \
             patch("zonny_core.deploy.env_scanner._probe_url", return_value=False):
            ctx, aws, gcp, azure = _detect_cloud()
        assert ctx == "local"
        assert aws is None
        assert gcp is None
        assert azure is None

    def test_docker_container(self, monkeypatch):
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        with patch("os.path.exists", return_value=True):
            ctx, aws, gcp, azure = _detect_cloud()
        assert ctx == "docker-container"

    def test_aws_ec2(self, monkeypatch):
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        monkeypatch.delenv("GCLOUD_PROJECT", raising=False)

        def _probe(url, **kw):
            return "169.254.169.254" in url and "meta-data/instance-id" in url

        with patch("os.path.exists", return_value=False), \
             patch("zonny_core.deploy.env_scanner._probe_url", side_effect=_probe), \
             patch("zonny_core.deploy.env_scanner._fetch_text", return_value="us-east-1"):
            ctx, aws, gcp, azure = _detect_cloud()
        assert ctx == "aws-ec2"
        assert aws == "us-east-1"

    def test_gcp(self, monkeypatch):
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
        monkeypatch.delenv("CLOUDSDK_CORE_PROJECT", raising=False)

        def _probe(url, **kw):
            # EC2 probe fails, GCP returns True
            if "google.internal" in url:
                return True
            return False

        with patch("os.path.exists", return_value=False), \
             patch("zonny_core.deploy.env_scanner._probe_url", side_effect=_probe), \
             patch("zonny_core.deploy.env_scanner._fetch_text", return_value="my-gcp-project"):
            ctx, aws, gcp, azure = _detect_cloud()
        assert ctx == "gcp-gce"
        assert gcp == "my-gcp-project"

    def test_azure(self, monkeypatch):
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
        monkeypatch.delenv("CLOUDSDK_CORE_PROJECT", raising=False)

        azure_response = json.dumps({"compute": {"subscriptionId": "abc-123"}})

        def _probe(url, **kw):
            # EC2 and GCP probe fail, Azure returns True
            if "metadata/instance" in url and "availability" not in url and "google" not in url:
                return True
            return False

        with patch("os.path.exists", return_value=False), \
             patch("zonny_core.deploy.env_scanner._probe_url", side_effect=_probe), \
             patch("zonny_core.deploy.env_scanner._fetch_text", return_value=azure_response):
            ctx, aws, gcp, azure = _detect_cloud()
        assert ctx == "azure-vm"
        assert azure == "abc-123"


# ── _detect_resources ─────────────────────────────────────────────────────────

class TestDetectResources:
    def test_psutil_available(self):
        mock_vm = MagicMock(total=16 * 1e9)
        mock_disk = MagicMock(free=100 * 1e9)

        with patch("zonny_core.deploy.env_scanner._PSUTIL", True), \
             patch("zonny_core.deploy.env_scanner.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = mock_vm
            mock_psutil.cpu_count.return_value = 8
            mock_psutil.disk_usage.return_value = mock_disk
            ram, cores, disk = _detect_resources()

        assert ram == pytest.approx(16.0, rel=0.01)
        assert cores == 8
        assert disk == pytest.approx(100.0, rel=0.01)

    def test_psutil_not_available(self):
        with patch("zonny_core.deploy.env_scanner._PSUTIL", False):
            ram, cores, disk = _detect_resources()
        assert ram == 0.0
        assert cores == 0
        assert disk == 0.0

    def test_psutil_exception_returns_zeros(self):
        with patch("zonny_core.deploy.env_scanner._PSUTIL", True), \
             patch("zonny_core.deploy.env_scanner.psutil") as mock_psutil:
            mock_psutil.virtual_memory.side_effect = RuntimeError("fail")
            ram, cores, disk = _detect_resources()
        assert ram == 0.0
        assert cores == 0
        assert disk == 0.0


# ── _infer_aws_region_from_az ─────────────────────────────────────────────────

class TestInferAwsRegion:
    def test_strips_trailing_letter(self):
        with patch("zonny_core.deploy.env_scanner._fetch_text", return_value="us-east-1a"):
            assert _infer_aws_region_from_az() == "us-east-1"

    def test_eu_west(self):
        with patch("zonny_core.deploy.env_scanner._fetch_text", return_value="eu-west-2b"):
            assert _infer_aws_region_from_az() == "eu-west-2"

    def test_no_az_data(self):
        with patch("zonny_core.deploy.env_scanner._fetch_text", return_value=None):
            assert _infer_aws_region_from_az() is None

    def test_short_string(self):
        with patch("zonny_core.deploy.env_scanner._fetch_text", return_value="us"):
            assert _infer_aws_region_from_az() is None


# ── EnvProfile serialisation ──────────────────────────────────────────────────

class TestEnvProfileSerialisation:
    def _make_profile(self) -> EnvProfile:
        return EnvProfile(
            os="linux",
            arch="x86_64",
            cloud_context="local",
            tools={"docker": True, "kubectl": False},
            docker_running=True,
            k8s_context="minikube",
            ram_gb=16.0,
            cpu_cores=8,
            disk_free_gb=100.0,
            ci=False,
        )

    def test_to_dict_contains_all_fields(self):
        p = self._make_profile()
        d = p.to_dict()
        assert d["os"] == "linux"
        assert d["arch"] == "x86_64"
        assert d["cloud_context"] == "local"
        assert d["tools"]["docker"] is True
        assert d["docker_running"] is True
        assert d["k8s_context"] == "minikube"
        assert d["ram_gb"] == 16.0
        assert d["cpu_cores"] == 8

    def test_to_json_is_valid(self):
        p = self._make_profile()
        parsed = json.loads(p.to_json())
        assert parsed["os"] == "linux"

    def test_round_trip_dict(self):
        p = self._make_profile()
        d = p.to_dict()
        restored = EnvProfile(**d)
        assert restored == p


# ── scan_env integration ──────────────────────────────────────────────────────

class TestScanEnv:
    """Integration-level: mock all I/O and assert scan_env() returns a populated EnvProfile."""

    def _patch_all(self, monkeypatch):
        """Remove all CI/cloud env vars and patch all I/O."""
        for var in ("GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "CI",
                    "CONTINUOUS_INTEGRATION", "AWS_DEFAULT_REGION",
                    "GCLOUD_PROJECT", "CLOUDSDK_CORE_PROJECT"):
            monkeypatch.delenv(var, raising=False)

    def test_returns_env_profile(self, monkeypatch):
        self._patch_all(monkeypatch)
        with patch("shutil.which", return_value="/usr/bin/tool"), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="minikube\n")), \
             patch("os.path.exists", return_value=False), \
             patch("zonny_core.deploy.env_scanner._probe_url", return_value=False), \
             patch("zonny_core.deploy.env_scanner._PSUTIL", False):
            result = scan_env()
        assert isinstance(result, EnvProfile)

    def test_cloud_context_local_when_no_imds(self, monkeypatch):
        self._patch_all(monkeypatch)
        with patch("shutil.which", return_value=None), \
             patch("os.path.exists", return_value=False), \
             patch("zonny_core.deploy.env_scanner._probe_url", return_value=False), \
             patch("zonny_core.deploy.env_scanner._PSUTIL", False):
            result = scan_env()
        assert result.cloud_context == "local"
        assert result.docker_running is False

    def test_github_actions_context(self, monkeypatch):
        self._patch_all(monkeypatch)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        with patch("shutil.which", return_value=None), \
             patch("zonny_core.deploy.env_scanner._PSUTIL", False):
            result = scan_env()
        assert result.ci is True
        assert result.ci_provider == "github-actions"
        assert result.cloud_context == "github-actions"

    def test_docker_running_when_daemon_alive(self, monkeypatch):
        self._patch_all(monkeypatch)

        def _which(name):
            return "/usr/bin/docker" if name == "docker" else None

        with patch("shutil.which", side_effect=_which), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="")), \
             patch("os.path.exists", return_value=False), \
             patch("zonny_core.deploy.env_scanner._probe_url", return_value=False), \
             patch("zonny_core.deploy.env_scanner._PSUTIL", False):
            result = scan_env()
        assert result.docker_running is True

    def test_resources_populated_when_psutil_present(self, monkeypatch):
        self._patch_all(monkeypatch)
        mock_vm = MagicMock(total=8 * 1e9)
        mock_disk = MagicMock(free=50 * 1e9)

        with patch("shutil.which", return_value=None), \
             patch("os.path.exists", return_value=False), \
             patch("zonny_core.deploy.env_scanner._probe_url", return_value=False), \
             patch("zonny_core.deploy.env_scanner._PSUTIL", True), \
             patch("zonny_core.deploy.env_scanner.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = mock_vm
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.disk_usage.return_value = mock_disk
            result = scan_env()

        assert result.ram_gb == pytest.approx(8.0, rel=0.01)
        assert result.cpu_cores == 4
        assert result.disk_free_gb == pytest.approx(50.0, rel=0.01)
