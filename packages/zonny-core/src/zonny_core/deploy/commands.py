"""zonny deploy — 6-command deployment pipeline (core/deterministic layer).

Pipeline:
  scan      → detect stack, write .zonny/deploy-profile.json
  plan      → (zonny-ai) read profile, rank strategies
  generate  → read profile+plan, write config files
  run       → execute deployment with live log streaming
  status    → show container/pod health and endpoint
  rollback  → revert to last known-good deployment snapshot
  cloudflare→ publish the running app via a Cloudflare Tunnel
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from zonny_core.deploy.env_scanner import scan_env
from zonny_core.deploy.generator import generate
from zonny_core.deploy.profile import DeployProfile
from zonny_core.deploy.runner import DeployError, run as _run_deploy
from zonny_core.deploy.scanner import scan
from zonny_core.utils.output import error, success, warn

app = typer.Typer(
    name="deploy",
    help="Smart application deployer — scan, plan, generate, run, monitor.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()

# Shared-state paths
_ZONNY_DIR      = Path(".zonny")
_PROFILE_PATH   = _ZONNY_DIR / "deploy-profile.json"
_PLAN_PATH      = _ZONNY_DIR / "deploy-plan.json"
_SNAPSHOT_PATH  = _ZONNY_DIR / "deploy-snapshot.json"
_DEPLOY_DIR     = _ZONNY_DIR / "generated"

_VALID_TARGETS = [
    "docker", "docker-compose", "kubernetes", "ecs-fargate", "ec2", "lambda",
    "fly.io", "railway", "cloud-run", "systemd", "process", "helm",
]


# ── Commands ──────────────────────────────────────────────────────────────────

@app.command(name="scan")
def scan_cmd(
    path: str = typer.Argument(".", help="Path to the project directory to scan."),
    output: Optional[str] = typer.Option(  # noqa: UP007
        None, "--output", "-o",
        help="Write profile JSON to this path (default: .zonny/deploy-profile.json).",
    ),
    show: bool = typer.Option(False, "--show", "-s", help="Print the detected profile."),
) -> None:
    """[bold]Scan[/bold] the project and detect its deployment profile.

    No user input required — Zonny reads language, framework, port, DB
    dependencies, environment variables, and more automatically.

    Results are written to [bold].zonny/deploy-profile.json[/bold] for use
    by subsequent deploy commands.
    """
    root = Path(path).resolve()
    if not root.is_dir():
        error(f"Directory not found: {path}")
        raise typer.Exit(1)

    with console.status("[bold green]Scanning project…[/bold green]"):
        profile = scan(root)

    out_path = Path(output) if output else _PROFILE_PATH
    profile.write(out_path)

    # ── Display summary ───────────────────────────────────────────────────────
    table = Table(title=f"Deploy Profile — {profile.project}", show_header=False)
    table.add_column("Key", style="bold cyan", width=20)
    table.add_column("Value")

    rows = [
        ("Language", f"{profile.language} {profile.runtime}"),
        ("Framework", profile.framework or "none"),
        ("Entry Point", profile.entry_point),
        ("Port", str(profile.port)),
        ("Build Cmd", profile.build_cmd),
        ("Start Cmd", profile.start_cmd),
        ("Databases", ", ".join(f"{d.type} ({d.orm})" for d in profile.databases) or "none"),
        ("Env Vars", ", ".join(profile.env_vars) or "none"),
        ("Static Assets", "yes" if profile.has_static else "no"),
        ("Est. Memory", profile.estimated_memory),
        ("Best Targets", " > ".join(profile.deploy_targets[:3])),
    ]
    for k, v in rows:
        table.add_row(k, v)

    console.print(table)
    
    # ── CONDITION 1: Ambiguity warnings ───────────────────────────────────────
    if profile.ambiguity.needs_ai:
        console.print()
        warn("Ambiguity detected — deterministic rules found multiple valid answers:")
        if profile.ambiguity.multiple_frameworks:
            console.print(f"  • Multiple frameworks: [yellow]{', '.join(profile.ambiguity.multiple_frameworks)}[/yellow]")
        if profile.ambiguity.multiple_entry_points:
            console.print(f"  • Multiple entry points: [yellow]{', '.join(profile.ambiguity.multiple_entry_points)}[/yellow]")
        if profile.ambiguity.conflicting_ports:
            console.print(f"  • Conflicting ports: [yellow]{', '.join(map(str, profile.ambiguity.conflicting_ports))}[/yellow]")
        console.print()
        console.print("[dim]Tip: Run [bold]zonny deploy refine[/bold] (requires zonny-ai) to use AI disambiguation[/dim]")
    
    console.print(f"\n[dim]Profile written to {out_path}[/dim]")
    console.print(
        "\n[dim]Next: [bold]zonny deploy plan[/bold] (requires zonny-ai) "
        "or [bold]zonny deploy generate[/bold][/dim]"
    )

    if show:
        console.print_json(json.dumps(profile.to_dict(), indent=2))


@app.command(name="generate")
def generate_cmd(
    target: Optional[str] = typer.Option(  # noqa: UP007
        None, "--target", "-t",
        help=f"Deploy target: {', '.join(_VALID_TARGETS)}. Uses plan recommendation if omitted.",
    ),
    profile_path: str = typer.Option(
        str(_PROFILE_PATH), "--profile",
        help="Path to deploy profile JSON.",
    ),
    out: str = typer.Option(
        str(_DEPLOY_DIR), "--out",
        help="Output directory for generated config files.",
    ),
) -> None:
    """[bold]Generate[/bold] deployment configuration files from the profile.

    Reads [bold].zonny/deploy-profile.json[/bold] (and optionally
    [bold].zonny/deploy-plan.json[/bold]) to produce the appropriate
    infrastructure files — Dockerfile, docker-compose.yml, k8s YAMLs, etc.
    """
    pp = Path(profile_path)
    if not pp.exists():
        error(
            f"Profile not found at {pp}. Run [bold]zonny deploy scan[/bold] first."
        )
        raise typer.Exit(1)

    profile = DeployProfile.load(pp)

    # Resolve target: explicit flag > plan recommendation > top of ranked list
    chosen_target = target
    if not chosen_target and _PLAN_PATH.exists():
        try:
            plan = json.loads(_PLAN_PATH.read_text())
            chosen_target = plan.get("recommended_target")
        except Exception:  # noqa: BLE001
            pass
    if not chosen_target:
        chosen_target = profile.deploy_targets[0] if profile.deploy_targets else "docker"

    if chosen_target not in _VALID_TARGETS:
        error(
            f"Unknown target '{chosen_target}'. Valid targets: {', '.join(_VALID_TARGETS)}"
        )
        raise typer.Exit(1)

    out_path = Path(out)
    with console.status(f"[bold green]Generating {chosen_target} config…[/bold green]"):
        generated = generate(profile, chosen_target, out_path)

    console.print(f"\n[bold green]✓[/bold green] Generated {len(generated)} file(s) for [bold]{chosen_target}[/bold]:")
    for f in generated:
        console.print(f"  [dim]{f}[/dim]")
    console.print(f"\n[dim]Next: [bold]zonny deploy run --target {chosen_target}[/bold][/dim]")


@app.command(name="run")
def run_cmd(
    target: Optional[str] = typer.Option(  # noqa: UP007
        None, "--target", "-t",
        help="Deploy target. Inferred from profile if omitted.",
    ),
    profile_path: str = typer.Option(str(_PROFILE_PATH), "--profile"),
    deploy_dir: str = typer.Option(str(_DEPLOY_DIR), "--dir"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the commands without executing."),
) -> None:
    """[bold]Run[/bold] the deployment with live log streaming.

    Executes the generated config files against the target infrastructure.
    On failure, the captured log is saved to [bold].zonny/last-error.log[/bold]
    — run [bold]zonny deploy diagnose[/bold] (requires zonny-ai) to get a fix.
    """
    pp = Path(profile_path)
    if not pp.exists():
        error("Profile not found. Run [bold]zonny deploy scan[/bold] first.")
        raise typer.Exit(1)

    profile = DeployProfile.load(pp)
    chosen_target = target or (profile.deploy_targets[0] if profile.deploy_targets else "docker")

    if dry_run:
        console.print(f"[bold yellow]Dry run[/bold yellow] — would deploy [bold]{profile.project}[/bold] to [bold]{chosen_target}[/bold]")
        return

    step_count = 0

    def _on_step(num: str, desc: str) -> None:
        nonlocal step_count
        step_count += 1
        console.print(f"  [bold cyan][{num}][/bold cyan] {desc}")

    console.print(f"\n[bold]Deploying [green]{profile.project}[/green] → {chosen_target}[/bold]\n")
    try:
        _run_deploy(profile, chosen_target, Path(deploy_dir), on_step=_on_step)
        success(f"\nDeployment complete! Access your app at http://localhost:{profile.port}")
    except DeployError as exc:
        # Save log for AI diagnosis
        err_log = _ZONNY_DIR / "last-error.log"
        _ZONNY_DIR.mkdir(exist_ok=True)
        err_log.write_text(exc.log, encoding="utf-8")
        error(f"Deployment failed: {exc}")
        console.print(
            f"\n[dim]Error log saved to {err_log}[/dim]\n"
            "[dim]Run [bold]zonny deploy diagnose[/bold] (requires zonny-ai) to get a fix.[/dim]"
        )
        raise typer.Exit(1) from exc


@app.command()
def status(
    target: Optional[str] = typer.Option(None, "--target", "-t"),  # noqa: UP007
    profile_path: str = typer.Option(str(_PROFILE_PATH), "--profile"),
) -> None:
    """Show the health and status of the running deployment."""
    pp = Path(profile_path)
    if not pp.exists():
        error("Profile not found. Run [bold]zonny deploy scan[/bold] first.")
        raise typer.Exit(1)

    profile = DeployProfile.load(pp)
    chosen_target = target or (profile.deploy_targets[0] if profile.deploy_targets else "docker")

    console.print(f"\n[bold]Deployment Status — {profile.project} ({chosen_target})[/bold]\n")

    if chosen_target in ("docker", "docker-compose"):
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={profile.project}", "--format",
                 "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.stdout.strip():
                console.print(result.stdout)
            else:
                warn(f"No running containers found for '{profile.project}'.")
        except FileNotFoundError:
            error("Docker is not installed or not on PATH.")
            raise typer.Exit(1)
    elif chosen_target == "kubernetes":
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "-l", f"app={profile.project}"],
                capture_output=True, text=True, timeout=15,
            )
            console.print(result.stdout or "No pods found.")
        except FileNotFoundError:
            error("kubectl is not installed or not on PATH.")
            raise typer.Exit(1)
    else:
        warn(f"Live status check not available for target '{chosen_target}'.")


@app.command()
def rollback(
    profile_path: str = typer.Option(str(_PROFILE_PATH), "--profile"),
    target: Optional[str] = typer.Option(None, "--target", "-t"),  # noqa: UP007
) -> None:
    """Revert to the last known-good deployment snapshot."""
    pp = Path(profile_path)
    if not pp.exists():
        error("Profile not found.")
        raise typer.Exit(1)

    profile = DeployProfile.load(pp)
    chosen_target = target or (profile.deploy_targets[0] if profile.deploy_targets else "docker")

    if chosen_target in ("docker", "docker-compose"):
        console.print("[bold yellow]Rolling back…[/bold yellow]")
        try:
            subprocess.run(
                ["docker", "compose", "down"],
                capture_output=False, timeout=30,
            )
            subprocess.run(
                ["docker", "compose", "up", "-d", "--scale", f"app=2"],
                capture_output=False, timeout=60,
            )
            success("Rollback complete.")
        except Exception as exc:  # noqa: BLE001
            error(f"Rollback failed: {exc}")
            raise typer.Exit(1) from exc
    elif chosen_target == "kubernetes":
        try:
            subprocess.run(
                ["kubectl", "rollout", "undo", f"deployment/{profile.project}"],
                capture_output=False, timeout=30,
            )
            success("Kubernetes rollout undone successfully.")
        except Exception as exc:  # noqa: BLE001
            error(f"Rollback failed: {exc}")
            raise typer.Exit(1) from exc
    else:
        warn(f"Automatic rollback is not supported for target '{chosen_target}'.")
        console.print("[dim]Manually restore from your last git tag or deployment snapshot.[/dim]")


@app.command(name="env")
def env_cmd() -> None:
    """[bold]Inspect[/bold] the current deployment environment.

    Detects OS, installed tools, cloud context (EC2 / GCP / Azure / local),
    kubectl context, system resources, and CI provider — no configuration
    required.
    """
    with console.status("[bold green]Scanning environment…[/bold green]"):
        profile = scan_env()

    # ── Summary table ─────────────────────────────────────────────────────
    table = Table(title="Environment Profile", show_header=False)
    table.add_column("Key", style="bold cyan", width=24)
    table.add_column("Value")

    # Format tools as a compact string
    available = [t for t, ok in profile.tools.items() if ok]
    missing   = [t for t, ok in profile.tools.items() if not ok]

    rows: list[tuple[str, str]] = [
        ("OS",             f"{profile.os} ({profile.arch})"),
        ("Cloud Context",  profile.cloud_context),
        ("CI",             f"{profile.ci_provider or 'no'}" if profile.ci else "no"),
        ("Docker Daemon",  "running" if profile.docker_running else "not running"),
        ("K8s Context",    profile.k8s_context or "none"),
        ("AWS Region",     profile.aws_region or "—"),
        ("GCP Project",    profile.gcp_project or "—"),
        ("Azure Sub",      profile.azure_subscription or "—"),
        ("RAM",            f"{profile.ram_gb} GB" if profile.ram_gb else "unknown"),
        ("CPU Cores",      str(profile.cpu_cores) if profile.cpu_cores else "unknown"),
        ("Disk Free",      f"{profile.disk_free_gb} GB" if profile.disk_free_gb else "unknown"),
        ("Tools Found",    ", ".join(available) or "none"),
        ("Tools Missing",  ", ".join(missing) or "none"),
    ]
    for k, v in rows:
        table.add_row(k, v)

    console.print(table)

    if not profile.docker_running and "docker" in missing:
        console.print("\n[dim]Tip: Install Docker to unlock docker / docker-compose / kubernetes targets.[/dim]")
    if not profile.tools.get("flyctl"):
        console.print("[dim]Tip: Install flyctl to unlock fly.io deployments.[/dim]")


@app.command(name="history")
def history_cmd(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of entries to display."),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON."),
    path: str = typer.Argument(".", help="Project directory (location of .zonny/)."),
) -> None:
    """[bold]Show deployment history[/bold] from .zonny/history.json.

    Displays the most recent deployments with their status, target, duration,
    and number of self-healing attempts. Entries with error details can be
    inspected further with [bold]zonny deploy diagnose[/bold].
    """
    history_path = Path(path).resolve() / ".zonny" / "history.json"
    if not history_path.exists():
        warn("No deploy history found. Run [bold]zonny deploy auto[/bold] first.")
        raise typer.Exit(0)

    try:
        entries: list = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        error(f"Could not read history file: {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(json.dumps(entries[:limit]))
        return

    table = Table(title="Deployment History", show_header=True, header_style="bold cyan")
    table.add_column("#",         width=3,  style="dim")
    table.add_column("ID",        width=9,  style="dim")
    table.add_column("Timestamp", width=22)
    table.add_column("Project",   width=16)
    table.add_column("Target",    width=14)
    table.add_column("Status",    width=10)
    table.add_column("Att.",      width=5,  justify="right")
    table.add_column("Duration",  width=10, justify="right")
    table.add_column("Via",       width=12)

    _status_styles = {
        "success":   "[bold green]success[/bold green]",
        "failed":    "[bold red]failed[/bold red]",
        "dev-error": "[bold yellow]dev-error[/bold yellow]",
    }

    for i, entry in enumerate(entries[:limit], 1):
        ts = entry.get("timestamp", "")[:19].replace("T", " ")
        styled_status = _status_styles.get(entry.get("status", ""), entry.get("status", "?"))
        dur = entry.get("duration_s")
        dur_str = f"{dur:.1f}s" if dur is not None else "—"
        health = entry.get("health")
        if health and entry.get("status") == "success":
            dur_str += f" [{health.get('latency_ms', 0):.0f}ms]"
        table.add_row(
            str(i),
            entry.get("id", "?"),
            ts,
            entry.get("project", "?"),
            entry.get("target", "?"),
            styled_status,
            str(entry.get("attempts", 1)),
            dur_str,
            entry.get("via", "?"),
        )

    console.print(table)

    # ── Show patches and fix suggestions for recent failures ──────────────────
    for entry in entries[:limit]:
        if entry.get("patches_applied"):
            console.print(
                f"\n[bold]{entry['id']}[/bold] patches applied:\n"
                + "\n".join(f"  • {p}" for p in entry["patches_applied"])
            )
        if entry.get("fix_suggestion"):
            console.print(
                f"\n[bold yellow]{entry['id']}[/bold yellow] fix suggestion:\n"
                f"  {entry['fix_suggestion']}"
            )


# -- Cloudflare Tunnel --------------------------------------------------------

@app.command(name="tunnels")
def tunnels_cmd() -> None:
    """List Cloudflare Tunnels detected on this machine."""
    from zonny_core.deploy.cloudflare import detect_tunnels  # noqa: PLC0415

    result = detect_tunnels()

    if not result.cloudflared_present:
        error("cloudflared not found.")
        console.print("[dim]Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/[/dim]")
        raise typer.Exit(1)

    if not result.tunnels:
        warn("No tunnels found (not authenticated or no tunnels created).")
        console.print("[dim]Run: cloudflared login[/dim]")
        raise typer.Exit(0)

    table = Table(title="Cloudflare Tunnels", show_header=True, header_style="bold cyan")
    table.add_column("Name",   style="bold")
    table.add_column("ID",     style="dim", width=38)
    table.add_column("Active", justify="center")
    table.add_column("Creds",  justify="center")
    table.add_column("Token",  justify="center")

    for t in result.tunnels:
        table.add_row(
            t.name,
            t.id,
            "[green]o[/green]" if t.active else "[dim]-[/dim]",
            "[green]yes[/green]" if t.has_creds else "[dim]no[/dim]",
            "[green]yes[/green]" if t.token else "[dim]no[/dim]",
        )

    console.print(table)
    console.print()
    console.print("[dim]Run [bold]zonny deploy cloudflare[/bold] to publish your app.[/dim]")


@app.command(name="cloudflare")
def cloudflare_cmd(
    port: int = typer.Option(
        0, "--port", "-p",
        help="Local port to expose. Defaults to port from deploy profile.",
    ),
    tunnel: Optional[str] = typer.Option(  # noqa: UP007
        None, "--tunnel", "-t",
        help="Tunnel name (e.g. Pixelstream). Auto-selects best available if omitted.",
    ),
    hostname: Optional[str] = typer.Option(  # noqa: UP007
        None, "--hostname", "-H",
        help="Full public hostname (e.g. lmh.zonny.me). Auto-derived from tunnel routes if omitted.",
    ),
    profile_path: str = typer.Option(str(_PROFILE_PATH), "--profile"),
) -> None:
    """Publish the running app publicly via Cloudflare Tunnel. Fully automated.

    Requires a one-time API token setup:

      zonny config set deploy.networking.cloudflare_tunnel.api_token <token>

    Get a token at https://dash.cloudflare.com/profile/api-tokens with:
      - Account > Cloudflare Tunnel > Edit
      - Zone > DNS > Edit

    After that, a single 'zonny deploy cloudflare' call will:
      [1] Detect tunnel and extract credentials from Windows service token
      [2] Determine public hostname (auto or --hostname)
      [3] Add / update the ingress rule via Cloudflare API
      [4] Create / update the DNS CNAME via Cloudflare API
      [5] Start cloudflared and connect to Cloudflare edge
      [6] Verify the URL is live and print it
    """
    from zonny_core.deploy.cloudflare import PublishError, auto_publish  # noqa: PLC0415

    # -- Resolve port ---------------------------------------------------------
    resolved_port = port
    if not resolved_port:
        pp = Path(profile_path)
        if pp.exists():
            try:
                resolved_port = DeployProfile(**json.loads(pp.read_text())).port
            except Exception:
                pass
    if not resolved_port:
        resolved_port = 8000

    # -- Check API token (env var > ~/.zonny/config.toml > nothing) -----------
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not api_token:
        _cfg_file = Path.home() / ".zonny" / "config.toml"
        if _cfg_file.exists():
            try:
                import sys as _sys
                if _sys.version_info >= (3, 11):
                    import tomllib as _tl
                else:
                    try:
                        import tomllib as _tl  # type: ignore[no-redef]
                    except ImportError:
                        import tomli as _tl  # type: ignore[no-redef,assignment]
                with open(_cfg_file, "rb") as _f:
                    _raw = _tl.load(_f)
                api_token = _raw.get("cloudflare", {}).get("api_token", "").strip()
            except Exception:
                pass

    if not api_token:
        console.print(
            "\n[bold yellow]Cloudflare API token not configured.[/bold yellow]\n"
        )
        console.print(
            "Get a token at [link=https://dash.cloudflare.com/profile/api-tokens]"
            "dash.cloudflare.com/profile/api-tokens[/link]\n"
            "Required permissions:\n"
            "  [bold]Account[/bold] > Cloudflare Tunnel > Edit\n"
            "  [bold]Zone[/bold]    > DNS > Edit\n"
        )
        console.print(
            "Then run [bold]once[/bold]:\n"
            "  [bold cyan]zonny config set cloudflare.api_token <YOUR_TOKEN>[/bold cyan]\n"
            "\n"
            "Or set the environment variable:\n"
            "  [bold cyan]$env:CLOUDFLARE_API_TOKEN = '<YOUR_TOKEN>'[/bold cyan]\n"
        )
        console.print(
            "After that, [bold]zonny deploy cloudflare[/bold] will handle everything automatically."
        )
        raise typer.Exit(1)

    # -- Run automation -------------------------------------------------------
    console.print(f"\n[bold]Publishing localhost:{resolved_port} via Cloudflare Tunnel[/bold]\n")

    status_icons = {"running": "[cyan]...[/cyan]", "ok": "[green]ok[/green]", "error": "[red]FAIL[/red]"}

    def _step(n: int, desc: str, status: str) -> None:
        icon = status_icons.get(status, "")
        if status == "running":
            console.print(f"  [dim][{n}/6][/dim] {desc}")
        elif status == "ok":
            console.print(f"  [green][{n}/6][/green] {desc}")
        else:
            console.print(f"  [red][{n}/6][/red] {desc}")

    try:
        public_url = auto_publish(
            port=resolved_port,
            api_token=api_token,
            tunnel_name=tunnel,
            hostname=hostname,
            step_cb=_step,
        )
    except PublishError as exc:
        error(str(exc))
        raise typer.Exit(1)

    console.print(
        f"\n[bold green]Live:[/bold green] [bold underline]{public_url}[/bold underline]\n"
        "[dim]cloudflared is running. Press Ctrl+C to stop.[/dim]"
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Tunnel stopped.[/dim]")






