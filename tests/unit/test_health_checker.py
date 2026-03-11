"""Unit tests for HealthChecker (health.py).

Uses unittest.mock to intercept httpx.get so no real HTTP calls are made.
Tests cover:
  - Successful responses (2xx, 3xx, 4xx all treated as "alive")
  - HTTP 5xx triggers retry
  - Connection errors trigger retry
  - Correct URL construction in smoke_test()
  - Retry count respected
  - Latency is recorded
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from zonny_core.deploy.health import HealthChecker, HealthResult


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_response(status_code: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    return r


# ── HealthResult dataclass ─────────────────────────────────────────────────────

class TestHealthResult:
    def test_fields_accessible(self) -> None:
        result = HealthResult(success=True, status_code=200, latency_ms=42.5, error=None)
        assert result.success is True
        assert result.status_code == 200
        assert result.latency_ms == 42.5
        assert result.error is None

    def test_failure_result(self) -> None:
        result = HealthResult(success=False, status_code=None, latency_ms=0.0, error="timeout")
        assert result.success is False
        assert result.error == "timeout"


# ── HealthChecker.check() ──────────────────────────────────────────────────────

class TestHealthCheckerCheck:
    def test_http_200_returns_success(self) -> None:
        with patch("httpx.get", return_value=_make_response(200)):
            result = HealthChecker().check("http://localhost:8000/health", retries=1)
        assert result.success is True
        assert result.status_code == 200
        assert result.error is None

    def test_http_404_returns_success(self) -> None:
        """404 means the app is alive even if the route doesn't exist."""
        with patch("httpx.get", return_value=_make_response(404)):
            result = HealthChecker().check("http://localhost:8000/health", retries=1)
        assert result.success is True
        assert result.status_code == 404

    def test_http_301_returns_success(self) -> None:
        with patch("httpx.get", return_value=_make_response(301)):
            result = HealthChecker().check("http://localhost:8000/", retries=1)
        assert result.success is True

    def test_http_500_triggers_retry_and_fails(self) -> None:
        """5xx responses should be retried; after all retries fail → success=False."""
        with patch("httpx.get", return_value=_make_response(500)) as mock_get:
            result = HealthChecker().check(
                "http://localhost:8000/health", retries=3, interval=0.0
            )
        assert result.success is False
        assert mock_get.call_count == 3

    def test_http_503_retries_exhausted(self) -> None:
        with patch("httpx.get", return_value=_make_response(503)):
            result = HealthChecker().check("http://localhost:8000/health", retries=2, interval=0.0)
        assert result.success is False
        assert result.error == "HTTP 503"

    def test_connection_error_retried(self) -> None:
        """Connection refused should be retried."""
        with patch("httpx.get", side_effect=ConnectionError("refused")) as mock_get:
            result = HealthChecker().check(
                "http://localhost:8000/", retries=3, interval=0.0
            )
        assert result.success is False
        assert result.error is not None
        assert mock_get.call_count == 3

    def test_succeeds_on_second_attempt(self) -> None:
        """Fail once, then succeed — should report success."""
        responses = [_make_response(500), _make_response(200)]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            r = responses[call_count]
            call_count += 1
            return r

        with patch("httpx.get", side_effect=side_effect):
            result = HealthChecker().check("http://localhost:8000/", retries=3, interval=0.0)

        assert result.success is True
        assert result.status_code == 200
        assert call_count == 2

    def test_latency_is_recorded(self) -> None:
        with patch("httpx.get", return_value=_make_response(200)):
            result = HealthChecker().check("http://localhost:8000/", retries=1)
        assert result.latency_ms >= 0.0

    def test_failure_result_has_no_latency(self) -> None:
        with patch("httpx.get", return_value=_make_response(500)):
            result = HealthChecker().check("http://localhost:8000/", retries=1, interval=0.0)
        assert result.latency_ms == 0.0

    def test_correct_url_called(self) -> None:
        with patch("httpx.get", return_value=_make_response(200)) as mock_get:
            HealthChecker().check("http://example.com/readyz", retries=1)
        mock_get.assert_called_once_with(
            "http://example.com/readyz", timeout=10.0, follow_redirects=True
        )


# ── HealthChecker.smoke_test() ────────────────────────────────────────────────

class TestSmokeTest:
    def test_smoke_test_constructs_localhost_url(self) -> None:
        with patch("httpx.get", return_value=_make_response(200)) as mock_get:
            HealthChecker().smoke_test(port=3000, path="/health")
        assert mock_get.call_args[0][0] == "http://localhost:3000/health"

    def test_smoke_test_default_path_is_health(self) -> None:
        with patch("httpx.get", return_value=_make_response(200)) as mock_get:
            HealthChecker().smoke_test(port=8000)
        assert "/health" in mock_get.call_args[0][0]

    def test_smoke_test_returns_health_result(self) -> None:
        with patch("httpx.get", return_value=_make_response(200)):
            result = HealthChecker().smoke_test(port=5000)
        assert isinstance(result, HealthResult)

    def test_smoke_test_failure(self) -> None:
        with patch("httpx.get", side_effect=ConnectionRefusedError("nope")):
            result = HealthChecker().smoke_test(port=9999)
        assert result.success is False
        assert result.error is not None

    def test_smoke_test_custom_path(self) -> None:
        with patch("httpx.get", return_value=_make_response(200)) as mock_get:
            HealthChecker().smoke_test(port=8080, path="/readyz")
        assert "readyz" in mock_get.call_args[0][0]
