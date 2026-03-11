"""zonny-ai deploy commands — AI-powered extensions to the core deploy pipeline.

Adds AI commands based on the four conditions:
  refine    — CONDITION 1: Disambiguate when scanner finds multiple valid answers
  plan      — CONDITION 2: Natural language strategy recommendation
  diagnose  — CONDITION 3: Failure diagnosis from logs + context
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from zonny_ai.deploy.planner import run_planner
from zonny_ai.llm.router import get_provider
from zonny_core.config.loader import load_config
from zonny_core.utils.output import error, print_panel, success

app = typer.Typer(
    name="deploy",
    help="AI-powered deploy planning and diagnostics.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()

_PROFILE_PATH = Path(".zonny/deploy-profile.json")
_PLAN_PATH    = Path(".zonny/deploy-plan.json")
_ERROR_LOG    = Path(".zonny/last-error.log")


@app.command()
def refine(
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),  # noqa: UP007
    profile_path: str = typer.Option(str(_PROFILE_PATH), "--profile"),
) -> None:
    """[bold]CONDITION 1:[/bold] Disambiguate ambiguous scan results with AI.
    
    When `zonny deploy scan` detects multiple frameworks, entry points, or ports,
    deterministic rules cannot decide which is correct. AI examines the actual
    code to determine which framework is truly used, which entry point is called,
    and which port is actually bound.
    
    This is [bold]Condition 1: Ambiguity[/bold] — when determinism produces
    multiple equally valid answers.
    """
    from zonny_core.deploy.profile import DeployProfile  # noqa: PLC0415
    
    pp = Path(profile_path)
    if not pp.exists():
        error(f"Profile not found: {pp}")
        error("Run [bold]zonny deploy scan[/bold] first")
        raise typer.Exit(1)
    
    profile = DeployProfile.load(pp)
    
    # Check if refinement is needed
    if not profile.ambiguity.needs_ai:
        from zonny_core.utils.output import info  # noqa: PLC0415
        info("No ambiguity detected — profile is already clear")
        console.print("[dim]Nothing to refine. Profile is deterministic.[/dim]")
        raise typer.Exit(0)
    
    # Show what needs disambiguation
    console.print("[bold yellow]Ambiguity detected:[/bold yellow]")
    if profile.ambiguity.multiple_frameworks:
        console.print(f"  • Multiple frameworks: {', '.join(profile.ambiguity.multiple_frameworks)}")
    if profile.ambiguity.multiple_entry_points:
        console.print(f"  • Multiple entry points: {', '.join(profile.ambiguity.multiple_entry_points)}")
    if profile.ambiguity.conflicting_ports:
        console.print(f"  • Conflicting ports: {', '.join(map(str, profile.ambiguity.conflicting_ports))}")
    
    # Get LLM
    try:
        cfg = load_config({})
        llm = get_provider(cfg, provider)
        if not llm.available():
            error(f"Provider '{llm.name()}' is not available. Check your API key.")
            raise typer.Exit(1)
    except Exception as exc:  # noqa: BLE001
        error(f"LLM setup failed: {exc}")
        raise typer.Exit(1) from exc
    
    # Build disambiguation prompt
    system = (
        "You are a deployment expert analyzing a codebase. "
        "Deterministic pattern matching found multiple valid answers. "
        "Read the code context and determine which answer is actually correct. "
        "Output ONLY valid JSON with keys: framework, entry_point, port. "
        "If a field is unambiguous, return the current value."
    )
    
    prompt = f"""Profile ambiguity analysis:

Project: {profile.project}
Language: {profile.language}

Current detection:
  Framework: {profile.framework}
  Entry Point: {profile.entry_point}
  Port: {profile.port}

Ambiguity:
  • Multiple frameworks detected: {profile.ambiguity.multiple_frameworks or 'none'}
  • Multiple entry points found: {profile.ambiguity.multiple_entry_points or 'none'}
  • Conflicting ports in code: {profile.ambiguity.conflicting_ports or 'none'}

Examine the actual code to determine:
1. Which framework is actually instantiated and used?
2. Which entry point is the real application entry?
3. Which port number is actually bound by the server?

Respond with JSON:
{{
  "framework": "<the actual framework>",
  "entry_point": "<the actual entry file>",
  "port": <the actual port number>,
  "rationale": "<brief explanation of how you determined this>"
}}
"""
    
    with console.status("[bold green]Disambiguating with AI...[/bold green]"):
        response = llm.generate(prompt, system)
    
    # Parse response
    import json  # noqa: PLC0415
    try:
        # Clean markdown fences if present
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.splitlines()[1:])
        if clean.endswith("```"):
            clean = "\n".join(clean.splitlines()[:-1])
        
        refined = json.loads(clean)
        
        # Update profile
        if "framework" in refined:
            profile.framework = refined["framework"]
        if "entry_point" in refined:
            profile.entry_point = refined["entry_point"]
        if "port" in refined:
            profile.port = int(refined["port"])
        
        # Mark as AI-refined and clear ambiguity
        profile.ai_refined = True
        profile.ambiguity.needs_ai = False
        
        # Rebuild start command with refined values
        from zonny_core.deploy.scanner import _detect_start_cmd  # noqa: PLC0415
        profile.start_cmd = _detect_start_cmd(
            profile.language,
            profile.framework,
            profile.entry_point,
            profile.port
        )
        
        # Save
        profile.write(pp)
        
        success("Profile refined with AI disambiguation")
        console.print(f"\n[bold]Refined values:[/bold]")
        console.print(f"  • Framework: [green]{profile.framework}[/green]")
        console.print(f"  • Entry Point: [green]{profile.entry_point}[/green]")
        console.print(f"  • Port: [green]{profile.port}[/green]")
        
        if "rationale" in refined:
            console.print(f"\n[dim]Rationale: {refined['rationale']}[/dim]")
        
    except json.JSONDecodeError:
        error("AI returned invalid JSON. Using original profile.")
        raise typer.Exit(1)


@app.command()
def plan(
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),  # noqa: UP007
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Use AI to [bold]recommend a deployment strategy[/bold].

    Reads [bold].zonny/deploy-profile.json[/bold] (run `zonny deploy scan` first)
    and returns a ranked list of deployment strategies with rationale.
    Output is written to [bold].zonny/deploy-plan.json[/bold].
    """
    try:
        cfg = load_config({})
        llm = get_provider(cfg, provider)
        if not llm.available():
            error(f"Provider '{llm.name()}' is not available. Check your API key.")
            raise typer.Exit(1)
    except Exception as exc:  # noqa: BLE001
        error(f"LLM setup failed: {exc}")
        raise typer.Exit(1) from exc

    with console.status("[bold green]Generating deployment strategy…[/bold green]"):
        run_planner(llm)

    import json
    plan_data = json.loads(_PLAN_PATH.read_text())

    success(f"Strategy saved to {_PLAN_PATH}")
    if json_output:
        console.print_json(json.dumps(plan_data))
    else:
        recommended = plan_data.get("recommended_target", "?")
        strategy    = plan_data.get("strategy", "")
        rationale   = plan_data.get("rationale", "")
        alts = plan_data.get("alternatives", [])
        warnings = plan_data.get("warnings", [])

        text = f"[bold green]Recommended:[/bold green] {recommended}\n\n"
        text += f"{strategy}\n\n"
        text += f"[dim]Why: {rationale}[/dim]\n"
        if alts:
            text += "\n[bold]Alternatives:[/bold]\n"
            for a in alts:
                text += f"  • {a['target']} — {a['reason']}\n"
        if warnings:
            text += "\n[bold yellow]Warnings:[/bold yellow]\n"
            for w in warnings:
                text += f"  ⚠ {w}\n"
        print_panel(text, title="Deployment Plan", border_style="blue")
        console.print(f"\n[dim]Next: [bold]zonny deploy generate[/bold][/dim]")


@app.command()
def diagnose(
    log: Optional[str] = typer.Option(None, "--log", "-l"),  # noqa: UP007
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),  # noqa: UP007
) -> None:
    """Use AI to [bold]diagnose a failed deployment[/bold].

    Reads the captured failure log (from the last `zonny deploy run` failure)
    and suggests a concrete fix.
    """
    log_path = Path(log) if log else _ERROR_LOG
    if not log_path.exists():
        error(f"No error log found at {log_path}. Run `zonny deploy run` first.")
        raise typer.Exit(1)

    log_content = log_path.read_text(encoding="utf-8", errors="replace")
    if not log_content.strip():
        error("Error log is empty.")
        raise typer.Exit(1)

    try:
        cfg = load_config({})
        llm = get_provider(cfg, provider)
    except Exception as exc:  # noqa: BLE001
        error(f"LLM setup failed: {exc}")
        raise typer.Exit(1) from exc

    from zonny_ai.llm.prompts import whybroke_prompt
    system, prompt = whybroke_prompt(log_content, "")
    prompt = "CI/Deploy System: docker/kubernetes\n\n" + prompt

    with console.status("[bold red]Diagnosing deployment failure…[/bold red]"):
        diagnosis = llm.generate(prompt, system)

    print_panel(diagnosis, title="Deployment Failure Diagnosis", border_style="red")


@app.command(name="auto")
def auto_cmd(
    path: str = typer.Argument(".", help="Path to the project directory."),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider override."),  # noqa: UP007
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    no_ai: bool = typer.Option(False, "--no-ai", help="Use deterministic target selection only."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Scan and plan without deploying."),
    max_tokens: int = typer.Option(512, hidden=True),
) -> None:
    """[bold]Auto-deploy[/bold] — scan, advise, generate, and run in one command.

    Zonny will:
    1. Detect your app stack (language, framework, port, databases)
    2. Detect your environment (OS, tools, cloud context)
    3. [AI] Resolve any ambiguity in the scan results  (Condition 1)
    4. [AI] Pick the best deployment target (Condition 2)
    5. Generate the required config files
    6. Deploy with live log streaming
    """
    import json as _json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from rich.table import Table  # noqa: PLC0415

    from zonny_ai.deploy.advisor import deterministic_target, run_advisor  # noqa: PLC0415
    from zonny_core.deploy.env_scanner import scan_env  # noqa: PLC0415
    from zonny_core.deploy.generator import generate  # noqa: PLC0415
    from zonny_core.deploy.profile import DeployProfile  # noqa: PLC0415
    from zonny_core.deploy.runner import DeployError  # noqa: PLC0415
    from zonny_core.deploy.runner import run as _run_deploy  # noqa: PLC0415
    from zonny_core.deploy.scanner import scan  # noqa: PLC0415

    root = Path(path).resolve()
    if not root.is_dir():
        error(f"Directory not found: {path}")
        raise typer.Exit(1)

    zonny_dir  = root / ".zonny"
    deploy_dir = zonny_dir / "generated"
    history_path = zonny_dir / "history.json"
    error_log    = zonny_dir / "last-error.log"

    # ── Step 1: Scan app ─────────────────────────────────────────────────────
    with console.status("[bold green]Scanning project…[/bold green]"):
        app_profile = scan(root)

    console.print(f"\n[bold]App:[/bold]  {app_profile.project}  "  
                  f"[cyan]{app_profile.language}[/cyan]/[cyan]{app_profile.framework or 'generic'}[/cyan]  "
                  f"port [cyan]{app_profile.port}[/cyan]  "
                  f"service-type [cyan]{getattr(app_profile, 'service_type', 'web')}[/cyan]")

    # ── Step 2: Scan environment ─────────────────────────────────────────────
    with console.status("[bold green]Scanning environment…[/bold green]"):
        env_profile = scan_env()

    avail_tools = [t for t, ok in env_profile.tools.items() if ok]
    console.print(f"[bold]Env:[/bold]  {env_profile.os}/{env_profile.arch}  "
                  f"cloud=[cyan]{env_profile.cloud_context}[/cyan]  "
                  f"docker=[cyan]{'yes' if env_profile.docker_running else 'no'}[/cyan]  "
                  f"tools=[cyan]{', '.join(avail_tools) or 'none'}[/cyan]\n")

    # ── Step 3: Initialise LLM (shared for C1, C2, and C3/C4 retry loop) ────
    _llm = None
    _deploy_cfg = None
    if not no_ai:
        try:
            cfg = load_config({})
            _deploy_cfg = cfg.deploy
            _llm = get_provider(cfg, provider)
            if not _llm.available():
                _llm = None
        except Exception:  # noqa: BLE001
            _llm = None

    # ── Condition 1 — resolve ambiguity ──────────────────────────────────────
    if app_profile.ambiguity.needs_ai and _llm is not None:
        console.print("[bold yellow]Ambiguity detected[/bold yellow] — asking AI to resolve…")
        try:
            _resolve_ambiguity(app_profile, _llm, console)
        except Exception:  # noqa: BLE001
            console.print("[dim]AI disambiguation failed — proceeding with best guess.[/dim]")

    # ── Condition 2 — pick target ─────────────────────────────────────────────
    if no_ai or _llm is None:
        recommendation = deterministic_target(app_profile, env_profile)
        if _llm is None and not no_ai:
            recommendation["warnings"].append("AI advisor unavailable — used deterministic rules.")
    else:
        try:
            with console.status("[bold green]Asking AI for deployment advice…[/bold green]"):
                recommendation = run_advisor(_llm, app_profile, env_profile)
        except Exception:  # noqa: BLE001
            recommendation = deterministic_target(app_profile, env_profile)
            recommendation["warnings"].append("AI advisor failed — used deterministic rules.")

    target = recommendation["target"]
    via    = recommendation.get("via", "deterministic")
    cost   = recommendation.get("monthly_cost_usd")
    cost_str = f"~${cost:.0f}/mo" if cost is not None else "varies"

    # ── Step 5: Show recommendation + confirm ──────────────────────────────
    table = Table(title="Deployment Recommendation", show_header=False)
    table.add_column("Key", style="bold cyan", width=18)
    table.add_column("Value")
    table.add_row("Target",    f"[bold green]{target}[/bold green]")
    table.add_row("Est. Cost", cost_str)
    table.add_row("Via",       via)
    table.add_row("Rationale", recommendation.get("rationale", ""))
    for w in recommendation.get("warnings", []):
        table.add_row("[yellow]Warning[/yellow]", w)
    console.print(table)

    if dry_run:
        console.print("\n[bold yellow]Dry run[/bold yellow] — stopping before generate/run.")
        raise typer.Exit(0)

    if not yes:
        typer.confirm(f"\nDeploy '{app_profile.project}' to '{target}'?", abort=True)

    # ── Step 6: Generate config files ─────────────────────────────────────
    with console.status(f"[bold green]Generating {target} config files…[/bold green]"):
        generated = generate(app_profile, target, deploy_dir)

    console.print(f"\n[bold green]✓[/bold green] Generated {len(generated)} file(s):")
    for f in generated:
        console.print(f"  [dim]{f.relative_to(root) if f.is_relative_to(root) else f}[/dim]")

    # ── Step 7: Self-healing deploy loop ──────────────────────────────────────
    from zonny_core.deploy.health import HealthChecker, HealthResult  # noqa: PLC0415
    from zonny_core.deploy.patcher import (  # noqa: PLC0415
        DiagnosisResult, apply_patch, classify_and_diagnose,
    )
    from zonny_core.utils.output import success as _success  # noqa: PLC0415
    import hashlib, datetime, time  # noqa: E401,PLC0415

    max_att        = (_deploy_cfg.max_attempts         if _deploy_cfg else 3)
    hc_path        = (_deploy_cfg.health_check_path    if _deploy_cfg else "/health")
    hc_retries     = (_deploy_cfg.health_check_retries if _deploy_cfg else 5)
    auto_rb        = (_deploy_cfg.auto_rollback        if _deploy_cfg else True)

    attempt        = 0
    status         = "success"
    err_msg        = ""
    error_class_v  = ""
    fix_suggestion = ""
    patches_applied: list[str] = []
    health_info:    dict = {}
    t0 = time.time()

    console.print(f"\n[bold]Deploying [green]{app_profile.project}[/green] → {target}[/bold]\n")

    while attempt < max_att:
        attempt += 1
        if attempt > 1:
            console.print(f"\n[bold yellow]Retry {attempt}/{max_att}[/bold yellow]…\n")

        deploy_log    = ""
        deploy_success = False
        try:
            _run_deploy(
                app_profile, target, deploy_dir,
                on_step=lambda n, d: console.print(f"  [bold cyan][{n}][/bold cyan] {d}"),
            )
            deploy_success = True
        except DeployError as exc:
            deploy_log = exc.log
            err_msg    = str(exc)
            zonny_dir.mkdir(exist_ok=True)
            error_log.write_text(exc.log, encoding="utf-8")
            error(f"Deployment failed: {exc}")

        if deploy_success:
            _success(f"\nDeploy step complete — running health check on port {app_profile.port}…")
            with console.status("[bold green]Health check…[/bold green]"):
                health: HealthResult = HealthChecker().smoke_test(app_profile.port, hc_path)

            if health.success:
                health_info = {"status_code": health.status_code, "latency_ms": health.latency_ms}
                _success(
                    f"Health check passed! HTTP {health.status_code} "
                    f"in {health.latency_ms:.0f} ms"
                )
                status = "success"
                break  # ✅ Done

            deploy_log = (
                f"Health check failed: {health.error or 'no response'}\n"
                f"Status code: {health.status_code}"
            )
            error(f"Health check failed: {health.error}")

        # ── Diagnose (C3 / C4) ───────────────────────────────────────────────
        if deploy_log and _llm is not None:
            with console.status("[bold red]Diagnosing failure…[/bold red]"):
                diagnosis: DiagnosisResult = classify_and_diagnose(deploy_log, _llm)
        else:
            diagnosis = DiagnosisResult(
                error_class="unknown",
                explanation="No AI available for diagnosis.",
                fix_suggestion="Inspect the error log at .zonny/last-error.log",
            )

        error_class_v = diagnosis.error_class
        console.print(f"\n[bold red]Diagnosis[/bold red] ({error_class_v}): {diagnosis.explanation}")

        if error_class_v == "development":
            # Condition 4 — stop retrying ─────────────────────────────────────
            status         = "dev-error"
            fix_suggestion = diagnosis.fix_suggestion
            from rich.panel import Panel  # noqa: PLC0415
            console.print(Panel(
                f"[bold red]Zonny stopped retrying.[/bold red]\n"
                f"This error is in your [bold]application code[/bold], "
                f"not in the deployment configuration.\n\n"
                f"[bold]Error:[/bold]   {err_msg[:120]}\n\n"
                f"[bold]Suggestion:[/bold]\n  {fix_suggestion}",
                title="[red]Development Error Detected[/red]",
                border_style="red",
            ))
            break

        if error_class_v == "deployment" and diagnosis.patch and attempt < max_att:
            # Condition 3 — apply patch + retry ──────────────────────────────
            applied = apply_patch(diagnosis.patch, deploy_dir)
            if applied:
                patches_applied.append(diagnosis.patch.description)
                console.print(
                    f"  [green]✓[/green] Patched: {diagnosis.patch.description}\n"
                    f"  [dim]File: {diagnosis.patch.file}[/dim]"
                )
                continue
            console.print(
                f"  [yellow]⚠[/yellow] Patch could not be applied "
                f"('{diagnosis.patch.file}' not found or snippet mismatch)."
            )

        if attempt >= max_att:
            status  = "failed"
            err_msg = deploy_log or err_msg or "Exhausted all retry attempts."
            break
        console.print(f"  [dim]Attempt {attempt}/{max_att} failed — retrying…[/dim]")

    # ── Rollback if completely failed ─────────────────────────────────────────
    if status == "failed" and auto_rb:
        console.print("\n[bold yellow]Auto-rollback triggered…[/bold yellow]")
        _attempt_rollback(target, app_profile, console)

    # ── Record history ────────────────────────────────────────────────────────
    entry: dict = {
        "id":        hashlib.sha1(f"{app_profile.project}{time.time()}".encode()).hexdigest()[:8],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "project":   app_profile.project,
        "target":    target,
        "status":    status,
        "duration_s": round(time.time() - t0, 1),
        "attempts":  attempt,
        "via":       via,
    }
    if err_msg:
        entry["error"] = err_msg[:500]
    if error_class_v:
        entry["error_class"] = error_class_v
    if fix_suggestion:
        entry["fix_suggestion"] = fix_suggestion
    if patches_applied:
        entry["patches_applied"] = patches_applied
    if health_info:
        entry["health"] = health_info

    zonny_dir.mkdir(exist_ok=True)
    history: list = []
    if history_path.exists():
        try:
            history = _json.loads(history_path.read_text())
        except Exception:  # noqa: BLE001
            history = []
    history.insert(0, entry)
    history_path.write_text(_json.dumps(history[:50], indent=2), encoding="utf-8")

    if status in ("failed", "dev-error"):
        raise typer.Exit(1)


def _attempt_rollback(target: str, profile: "DeployProfile", console) -> None:  # type: ignore[type-arg]
    """Best-effort rollback to the last known-good state for *target*."""
    import subprocess  # noqa: PLC0415

    rollback_cmds: dict[str, list[list[str]]] = {
        "docker":         [["docker", "compose", "down"], ["docker", "compose", "up", "-d"]],
        "docker-compose": [["docker", "compose", "down"], ["docker", "compose", "up", "-d"]],
        "kubernetes":     [["kubectl", "rollout", "undo", f"deployment/{profile.project}"]],
        "helm":           [["helm", "rollback", profile.project, "0"]],
        "fly.io":         [["flyctl", "deploy", "--strategy", "canary", "--rollback"]],
        "cloud-run":      [],  # gcloud revisions need prior revision name — skip silently
        "railway":        [["railway", "rollback"]],
    }
    cmds = rollback_cmds.get(target, [])
    if not cmds:
        console.print(f"  [dim]Automatic rollback not supported for target '{target}'.[/dim]")
        return
    for cmd in cmds:
        try:
            subprocess.run(cmd, capture_output=False, timeout=60, check=False)  # noqa: S603
        except Exception as exc:  # noqa: BLE001
            console.print(f"  [yellow]Rollback step failed: {exc}[/yellow]")


def _resolve_ambiguity(profile: "DeployProfile", llm, console) -> None:  # type: ignore[type-arg]
    """Inline C1 resolution — updates profile in-place."""
    import json as _json  # noqa: PLC0415
    system = (
        "You are a deployment expert. Deterministic pattern matching found multiple valid answers. "
        "Read the code context and determine which answer is actually correct. "
        "Output ONLY valid JSON with keys: framework, entry_point, port, rationale."
    )
    prompt = (
        f"Project: {profile.project}\nLanguage: {profile.language}\n"
        f"Multiple frameworks: {profile.ambiguity.multiple_frameworks}\n"
        f"Multiple entry points: {profile.ambiguity.multiple_entry_points}\n"
        f"Conflicting ports: {profile.ambiguity.conflicting_ports}\n"
        "Determine the correct framework, entry_point, and port."
    )
    try:
        raw = llm.generate(prompt, system, max_tokens=256)
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        refined = _json.loads(clean)
        if "framework"   in refined: profile.framework   = refined["framework"]
        if "entry_point" in refined: profile.entry_point = refined["entry_point"]
        if "port"        in refined: profile.port        = int(refined["port"])
        profile.ai_refined = True
        profile.ambiguity.needs_ai = False
        console.print(f"  [dim]Resolved: {refined.get('framework')} / {refined.get('entry_point')} / port {refined.get('port')}[/dim]")
    except Exception:  # noqa: BLE001
        pass  # silently fall through — ambiguity remains, not fatal
