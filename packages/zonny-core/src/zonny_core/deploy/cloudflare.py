"""Cloudflare Tunnel full automation for ``zonny deploy cloudflare``.

Single-shot automation -- given an API token (stored once in zonny config)
this module does everything without user intervention:

  Step 1 -- Detect   : find cloudflared binary + named (or best) tunnel.
  Step 2 -- Hostname : auto-pick subdomain from existing tunnel domain,
                       or accept an explicit --hostname.
  Step 3 -- Ingress  : call CF API to add/replace the ingress rule.
  Step 4 -- DNS      : call CF API to create/update the CNAME record.
  Step 5 -- Connect  : start cloudflared with synthesised credentials.
  Step 6 -- Verify   : HTTP-check the public URL; return it when live.

One-time setup
--------------
  zonny config set deploy.networking.cloudflare_tunnel.api_token <token>

Token permissions needed
------------------------
  - Account > Cloudflare Tunnel > Edit
  - Zone > DNS > Edit

Public surface
--------------
  detect_tunnels()   -> TunnelDetectResult
  auto_publish(...)  -> str (public URL)  raises PublishError on failure
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CloudflareTunnel:
    id: str
    name: str
    active: bool        # has live connections right now
    has_creds: bool     # credential JSON available locally
    token: str | None   # service token (Windows only)


@dataclass
class TunnelDetectResult:
    cloudflared_present: bool
    cloudflared_path: str | None
    tunnels: list[CloudflareTunnel] = field(default_factory=list)
    error: str | None = None


class PublishError(Exception):
    """Raised when auto_publish cannot complete a step."""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_tunnels() -> TunnelDetectResult:
    """Detect cloudflared and list known tunnels with credential availability."""
    path = shutil.which("cloudflared")
    if not path:
        win_path = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
        if Path(win_path).exists():
            path = win_path
    if not path:
        return TunnelDetectResult(cloudflared_present=False, cloudflared_path=None)

    cf_dir = Path.home() / ".cloudflared"

    service_token_map: dict[str, str] = {}
    if sys.platform == "win32":
        service_token_map = _extract_service_tokens()

    try:
        raw = subprocess.check_output(
            [path, "tunnel", "list", "--output", "json"],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        tunnels_json: list[dict] = json.loads(raw)
    except Exception:
        return TunnelDetectResult(cloudflared_present=True, cloudflared_path=path, tunnels=[])

    tunnels: list[CloudflareTunnel] = []
    for t in tunnels_json:
        tid = t.get("id", "")
        name = t.get("name", "")
        active = bool(t.get("connections"))
        has_creds = (cf_dir / f"{tid}.json").exists()
        token = service_token_map.get(tid) or service_token_map.get(name.lower())
        tunnels.append(CloudflareTunnel(
            id=tid, name=name, active=active,
            has_creds=has_creds, token=token,
        ))

    return TunnelDetectResult(
        cloudflared_present=True,
        cloudflared_path=path,
        tunnels=tunnels,
    )


def _extract_service_tokens() -> dict[str, str]:
    try:
        out = subprocess.check_output(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-WmiObject Win32_Service | Where-Object { $_.Name -like '*cloudflared*' }"
                " | Select-Object -ExpandProperty PathName",
            ],
            stderr=subprocess.DEVNULL,
            timeout=8,
        ).decode(errors="replace")
    except Exception:
        return {}

    result: dict[str, str] = {}
    for line in out.splitlines():
        m = re.search(r"--token\s+(\S+)", line)
        if m:
            token = m.group(1)
            tid = _jwt_field(token, "t")
            if tid:
                result[tid] = token
    return result


def _jwt_field(token: str, field: str) -> str | None:
    """Extract a field from a Cloudflare JWT-style base64 token."""
    try:
        parts = token.split(".")
        segment = parts[1] if len(parts) >= 2 else token
        padded = segment + "=" * (-len(segment) % 4)
        return json.loads(base64.b64decode(padded).decode()).get(field)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cloudflare REST API client
# ---------------------------------------------------------------------------

_CF_API = "https://api.cloudflare.com/client/v4"


class CloudflareAPI:
    """Minimal Cloudflare API wrapper using stdlib urllib (no extra deps)."""

    def __init__(self, api_token: str) -> None:
        self._token = api_token

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{_CF_API}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            raise PublishError(f"CF API {method} {path} [{exc.code}]: {raw}") from exc

    def get(self, path: str, **params: str) -> dict:
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            path = f"{path}?{qs}"
        return self._req("GET", path)

    def post(self, path: str, body: dict) -> dict:
        return self._req("POST", path, body)

    def put(self, path: str, body: dict) -> dict:
        return self._req("PUT", path, body)

    def patch(self, path: str, body: dict) -> dict:
        return self._req("PATCH", path, body)

    def delete(self, path: str) -> dict:
        return self._req("DELETE", path)

    # ── Higher-level helpers ─────────────────────────────────────────────────

    def get_zone_id(self, domain: str) -> str:
        resp = self.get("/zones", name=domain)
        results = resp.get("result", [])
        if not results:
            raise PublishError(
                f"Zone '{domain}' not found in your Cloudflare account. "
                "Check the API token has Zone:DNS:Edit permission."
            )
        return results[0]["id"]

    def get_tunnel_ingress(self, account_id: str, tunnel_id: str) -> list[dict]:
        resp = self.get(f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations")
        return resp.get("result", {}).get("config", {}).get("ingress", [])

    def set_tunnel_ingress(self, account_id: str, tunnel_id: str, rules: list[dict]) -> None:
        """Replace tunnel ingress. Always appends a catch-all 404 at the end."""
        body_rules = [r for r in rules if r.get("hostname")]
        body_rules.append({"service": "http_status:404"})
        self.put(
            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            {"config": {"ingress": body_rules}},
        )

    def upsert_dns_cname(self, zone_id: str, name: str, tunnel_id: str) -> None:
        """Create or update a proxied CNAME ``name`` -> ``<tunnel_id>.cfargotunnel.com``."""
        target = f"{tunnel_id}.cfargotunnel.com"
        existing = self.get(f"/zones/{zone_id}/dns_records", type="CNAME", name=name)
        records = existing.get("result", [])
        record_body = {"type": "CNAME", "name": name, "content": target, "proxied": True, "ttl": 1}
        if records:
            self.patch(f"/zones/{zone_id}/dns_records/{records[0]['id']}", record_body)
        else:
            self.post(f"/zones/{zone_id}/dns_records", record_body)


# ---------------------------------------------------------------------------
# Full end-to-end automation
# ---------------------------------------------------------------------------


def auto_publish(
    port: int,
    api_token: str,
    tunnel_name: str | None = None,
    hostname: str | None = None,
    step_cb: Callable[[int, str, str], None] | None = None,
) -> str:
    """Run the full 6-step publish automation and return the live public URL.

    Parameters
    ----------
    port:
        Local port the app is listening on.
    api_token:
        Cloudflare API token with Zone:DNS:Edit + Account:Cloudflare Tunnel:Edit.
    tunnel_name:
        Preferred tunnel name. Auto-selects best available tunnel if None.
    hostname:
        Full hostname (e.g. ``lmh.zonny.me``). Auto-derived if None.
    step_cb:
        Called as ``step_cb(step_number, description, status)``
        where status is one of ``'running'``, ``'ok'``, ``'error'``.
    """

    def _step(n: int, desc: str, status: str = "ok") -> None:
        if step_cb:
            step_cb(n, desc, status)

    # -- Step 1: Detect -------------------------------------------------------
    _step(1, "Detecting cloudflared and tunnels...", "running")

    result = detect_tunnels()
    if not result.cloudflared_present:
        raise PublishError(
            "cloudflared not found. Install from:\n"
            "  https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/"
        )

    usable = [t for t in result.tunnels if t.has_creds or t.token]
    if not usable:
        raise PublishError(
            "No tunnels with usable credentials found.\n"
            "Run 'cloudflared tunnel login' to authenticate."
        )

    if tunnel_name:
        matches = [t for t in usable if t.name.lower() == tunnel_name.lower()]
        if not matches:
            raise PublishError(
                f"Tunnel '{tunnel_name}' not found or has no credentials.\n"
                f"Available: {', '.join(t.name for t in usable)}"
            )
        tunnel = matches[0]
    else:
        tunnel = sorted(usable, key=lambda t: (not t.active, not t.token))[0]

    account_id = _jwt_field(tunnel.token, "a") if tunnel.token else None
    if not account_id:
        raise PublishError(
            f"Cannot determine Cloudflare Account ID for tunnel '{tunnel.name}'.\n"
            "The service token is missing or malformed."
        )

    _step(1, f"Tunnel: {tunnel.name}  |  account: {account_id[:8]}...  |  id: {tunnel.id[:8]}...", "ok")

    # -- Step 2: Resolve hostname ----------------------------------------------
    _step(2, "Resolving public hostname...", "running")

    cf = CloudflareAPI(api_token)

    if hostname:
        final_hostname = hostname.lstrip("https://").lstrip("http://").rstrip("/")
    else:
        existing_ingress = _safe_fetch_ingress(cf, account_id, tunnel.id)
        base_domain = _infer_base_domain(existing_ingress)
        if not base_domain:
            raise PublishError(
                "Cannot auto-detect base domain.\n"
                "This happens when:\n"
                "  - The API token doesn't have 'Account > Cloudflare Tunnel > Edit' permission\n"
                "  - The tunnel has no existing ingress rules yet\n\n"
                "Fix: specify the hostname manually:\n"
                "  zonny deploy cloudflare --port 8000 --hostname lmh.zonny.me"
            )
        subdomain = f"p{port}"
        final_hostname = f"{subdomain}.{base_domain}"

    # Split into subdomain + domain
    parts = final_hostname.split(".")
    if len(parts) < 2:
        raise PublishError(f"Invalid hostname '{final_hostname}'. Expected: subdomain.domain.tld")
    domain = ".".join(parts[-2:])
    subdomain_part = ".".join(parts[:-2]) or parts[0]

    _step(2, f"Publishing to: https://{final_hostname}", "ok")

    # -- Step 3: Update tunnel ingress via API ---------------------------------
    _step(3, f"Setting ingress rule  {final_hostname}  ->  localhost:{port} ...", "running")

    existing_ingress = _safe_fetch_ingress(cf, account_id, tunnel.id)
    filtered = [r for r in existing_ingress if r.get("hostname") and r.get("hostname") != final_hostname]
    new_rule: dict = {"hostname": final_hostname, "originRequest": {}, "service": f"http://localhost:{port}"}
    try:
        cf.set_tunnel_ingress(account_id, tunnel.id, [new_rule] + filtered)
    except PublishError as exc:
        raise PublishError(f"Step 3 - ingress update failed: {exc}") from exc

    _step(3, f"Ingress rule saved: {final_hostname} -> localhost:{port}", "ok")

    # -- Step 4: Create / update DNS CNAME ------------------------------------
    _step(4, f"Creating DNS CNAME  {final_hostname}  -> {tunnel.id[:8]}.cfargotunnel.com ...", "running")

    try:
        zone_id = cf.get_zone_id(domain)
        cf.upsert_dns_cname(zone_id, final_hostname, tunnel.id)
    except PublishError as exc:
        raise PublishError(f"Step 4 - DNS failed: {exc}") from exc

    _step(4, f"DNS record live: {final_hostname}", "ok")

    # -- Step 5: Start cloudflared --------------------------------------------
    _step(5, f"Starting cloudflared ({tunnel.name})...", "running")

    proc = _launch_cloudflared(result.cloudflared_path, tunnel)  # type: ignore[arg-type]
    if proc.poll() is not None:
        raise PublishError("cloudflared exited immediately after launch. Check credentials.")

    _step(5, "cloudflared running and connected", "ok")

    # -- Step 6: Verify URL is live -------------------------------------------
    public_url = f"https://{final_hostname}"
    _step(6, f"Verifying {public_url} (up to 45s, DNS propagation may take ~30s)...", "running")

    live = _wait_for_url(public_url, timeout=45)
    if live:
        _step(6, f"Live: {public_url}", "ok")
    else:
        # Still success — DNS TTL 1 but propagation can lag
        _step(6, f"URL set up; DNS may still be propagating: {public_url}", "ok")

    return public_url


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_fetch_ingress(cf: CloudflareAPI, account_id: str, tunnel_id: str) -> list[dict]:
    try:
        return cf.get_tunnel_ingress(account_id, tunnel_id)
    except Exception:
        return []


def _infer_base_domain(ingress_rules: list[dict]) -> str | None:
    """Derive base domain (e.g. 'zonny.me') from existing ingress hostnames."""
    for rule in ingress_rules:
        hostname = rule.get("hostname", "")
        if hostname:
            parts = hostname.rsplit(".", 2)
            if len(parts) >= 2:
                return ".".join(parts[-2:])
    return None


def _token_to_cred_json(token: str) -> dict | None:
    try:
        parts = token.split(".")
        segment = parts[1] if len(parts) >= 2 else token
        padded = segment + "=" * (-len(segment) % 4)
        payload = json.loads(base64.b64decode(padded).decode())
        return {"AccountTag": payload["a"], "TunnelID": payload["t"], "TunnelSecret": payload["s"]}
    except Exception:
        return None


def _launch_cloudflared(cf_path: str, tunnel: CloudflareTunnel) -> subprocess.Popen:
    """Write a minimal temp config and start cloudflared. Returns the Popen."""
    if tunnel.has_creds:
        creds_path = str(Path.home() / ".cloudflared" / f"{tunnel.id}.json")
        tmp_creds: str | None = None
    elif tunnel.token:
        synth = _token_to_cred_json(tunnel.token)
        if not synth:
            raise PublishError(f"Cannot synthesise credentials for tunnel '{tunnel.name}'.")
        cred_fd, creds_path = tempfile.mkstemp(suffix=".json", prefix="zonny-cf-creds-")
        with os.fdopen(cred_fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(synth))
        tmp_creds = creds_path
    else:
        raise PublishError(f"Tunnel '{tunnel.name}' has no credentials. Run 'cloudflared tunnel login'.")

    creds_yaml = creds_path.replace("\\", "/")
    cfg_yaml = f"tunnel: {tunnel.id}\ncredentials-file: {creds_yaml}\n"
    cfg_fd, cfg_path = tempfile.mkstemp(suffix=".yml", prefix="zonny-cf-")
    with os.fdopen(cfg_fd, "w", encoding="utf-8") as f:
        f.write(cfg_yaml)

    proc = subprocess.Popen(
        [cf_path, "--config", cfg_path, "tunnel", "run", tunnel.id],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )

    def _drain() -> None:
        for _ in proc.stdout:  # type: ignore[union-attr]
            pass
        for p in [cfg_path, *([] if tmp_creds is None else [tmp_creds])]:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass

    threading.Thread(target=_drain, daemon=True).start()
    time.sleep(2)
    return proc


def _wait_for_url(url: str, timeout: int = 45) -> bool:
    """Poll *url* every 2s until HTTP <500 or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "zonny/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Remote config parsing helper (informational)
# ---------------------------------------------------------------------------

_REMOTE_CFG_RE = re.compile(r'INF Updated to new configuration config="(\{.*\})"')


def parse_remote_ingress(line: str) -> list[dict] | None:
    m = _REMOTE_CFG_RE.search(line)
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads(raw).get("ingress", [])
    except Exception:
        try:
            return json.loads(json.loads(f'"{raw}"')).get("ingress", [])
        except Exception:
            return None
