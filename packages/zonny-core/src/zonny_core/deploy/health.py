"""HealthChecker — HTTP smoke tests for deployed applications.

Used by the self-healing retry loop in ``zonny deploy auto`` to verify
that the app is alive after deployment.

Two usage patterns:

    # Full URL (external service, CI, etc.)
    result = HealthChecker().check("https://my-app.fly.dev/health")

    # Local port shorthand (most common for local deploys)
    result = HealthChecker().smoke_test(port=8000)
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class HealthResult:
    """Result of a single health-check sequence."""

    success: bool
    status_code: int | None
    latency_ms: float
    error: str | None


class HealthChecker:
    """Polls an HTTP endpoint and reports whether the app is alive.

    Any HTTP response with a status code below 500 is treated as *alive*
    (the app is running even if it returns 404 — that is a routing issue,
    not a startup crash). HTTP 5xx and connection errors are retried.
    """

    def check(
        self,
        url: str,
        retries: int = 5,
        interval: float = 2.0,
        timeout: float = 10.0,
    ) -> HealthResult:
        """Poll *url* up to *retries* times, pausing *interval* seconds between
        each attempt. Returns on the first success (< 500) or after exhausting
        all retries.

        Args:
            url:      Full URL to poll (e.g. ``http://localhost:8000/health``).
            retries:  Maximum number of attempts before reporting failure.
            interval: Seconds to wait between failed attempts.
            timeout:  Per-request timeout in seconds.

        Returns:
            :class:`HealthResult` — ``success=True`` as soon as the app responds
            with a non-5xx status code; ``success=False`` after all retries fail.
        """
        import httpx  # noqa: PLC0415 — optional at import time

        last_error: str | None = None
        last_code: int | None = None

        for attempt in range(retries):
            try:
                t0 = time.perf_counter()
                response = httpx.get(url, timeout=timeout, follow_redirects=True)
                latency = (time.perf_counter() - t0) * 1000.0
                last_code = response.status_code

                if response.status_code < 500:
                    return HealthResult(
                        success=True,
                        status_code=response.status_code,
                        latency_ms=round(latency, 1),
                        error=None,
                    )

                last_error = f"HTTP {response.status_code}"

            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                last_code = None

            if attempt < retries - 1:
                time.sleep(interval)

        return HealthResult(
            success=False,
            status_code=last_code,
            latency_ms=0.0,
            error=last_error,
        )

    def smoke_test(self, port: int, path: str = "/health") -> HealthResult:
        """Shorthand: check ``http://localhost:<port><path>``.

        This is the most common usage — called immediately after a local
        deployment to verify the app started successfully.

        Args:
            port: The port the app is expected to listen on.
            path: Health-check endpoint path (default ``/health``).
                  Falls back gracefully to ``/`` if ``/health`` returns 404,
                  since a 404 still means the app is running.
        """
        return self.check(f"http://localhost:{port}{path}", retries=5, interval=2.0)
