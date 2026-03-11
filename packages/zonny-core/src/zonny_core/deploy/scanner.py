"""Stack detection engine — the heart of `zonny deploy scan`.

Uses multi-signal detection to infer everything needed for deployment
from the repository itself, with no user input required.

Language support (Phase 1 + Phase 2):
  python, node, typescript, java, go, ruby,
  rust, php, dotnet, dart, static
Service types: web, worker, static, cron, multi (monorepo)
"""
from __future__ import annotations

import re
from pathlib import Path

from zonny_core.deploy.profile import DBDependency, DeployProfile

# ── Detection tables ───────────────────────────────────────────────────────────

_LANG_SIGNALS: dict[str, list[str]] = {
    "python":     ["requirements.txt", "setup.py", "setup.cfg", "pyproject.toml", "Pipfile"],
    "node":       ["package.json"],
    "java":       ["pom.xml", "build.gradle", "build.gradle.kts"],
    "go":         ["go.mod"],
    "ruby":       ["Gemfile"],
    "rust":       ["Cargo.toml"],
    "php":        ["composer.json"],
    "dart":       ["pubspec.yaml"],
    # dotnet: *.csproj / *.sln glob — detected specially in _detect_language
}

_FRAMEWORK_PATTERNS: dict[str, list[str]] = {
    # Python
    "fastapi":    [r"from fastapi", r"import fastapi"],
    "flask":      [r"from flask", r"import flask"],
    "django":     [r"from django", r"import django", r"django.setup"],
    # Node / TypeScript
    "express":    [r"require\(['\"]express['\"]", r"from ['\"]express['\"]"],
    "fastify":    [r"require\(['\"]fastify['\"]"],
    "nextjs":     [r"next/app", r"next/router", r"from 'next'"],
    "nuxt":       [r"from ['\"]nuxt", r"defineNuxtConfig"],
    "svelte":     [r"from ['\"]svelte", r"SvelteKit"],
    # Java
    "spring":     [r"@SpringBootApplication", r"import org\.springframework"],
    # Go
    "gin":        [r"github\.com/gin-gonic/gin", r'"gin"'],
    "echo":       [r"github\.com/labstack/echo"],
    # Ruby
    "rails":      [r"require ['\"]rails['\"]", r"Rails\.application"],
    # Rust
    "actix-web":  [r"actix_web", r"HttpServer::new"],
    "axum":       [r"axum::", r"Router::new"],
    "rocket":     [r"#\[macro_use\]\s*extern crate rocket", r"rocket::build"],
    "warp":       [r"warp::", r"warp::Filter"],
    # PHP
    "laravel":    [r"Illuminate\\\\", r"artisan", r"Laravel"],
    "symfony":    [r"Symfony\\\\", r"symfony/framework-bundle"],
    "wordpress":  [r"wp_enqueue", r"add_action", r"WP_Query"],
    # .NET
    "aspnetcore": [r"Microsoft\.AspNetCore", r"WebApplication\.Create", r"app\.MapGet"],
    "blazor":     [r"@namespace.*Blazor", r"Microsoft\.AspNetCore\.Components"],
    # Dart / Flutter
    "flutter":    [r"package:flutter", r"runApp\("],
    "shelf":      [r"package:shelf", r"shelf\.Response"],
}

_PORT_PATTERNS = [
    r"app\.listen\((\d+)",           # Express / Node
    r"--port[= ](\d+)",              # uvicorn / gunicorn CLI
    r"port\s*=\s*(\d+)",             # generic assignment
    r"PORT\s*\|\|\s*(\d+)",          # process.env.PORT || 3000
    r"server\.port\s*=\s*(\d+)",     # Spring
    r"listen_addr.*:(\d+)",          # Go
    r'\.bind\("[\d.]*:(\d+)"\)',     # Axum / Actix-web Rust
]

# ── Service-type classification patterns ──────────────────────────────────────

_WORKER_PATTERNS = [
    # Python
    r"celery", r"from rq import", r"import rq", r"dramatiq", r"huey",
    # Node/TS
    r"bullmq", r"bull\.Queue", r"amqplib", r"kafkajs",
    # Ruby
    r"Sidekiq", r"sidekiq",
]

_CRON_PATTERNS = [
    # Python
    r"apscheduler", r"schedule\.every", r"BackgroundScheduler",
    # Node/TS
    r"node-cron", r"cron\.schedule", r"CronJob",
    # General
    r"cron_job", r"@Scheduled",
]

_DB_SIGNALS: dict[str, dict[str, list[str]]] = {
    "python": {
        "postgresql": ["psycopg2", "asyncpg", "sqlalchemy", "databases"],
        "mysql":      ["pymysql", "mysqlclient", "aiomysql"],
        "mongodb":    ["pymongo", "motor", "mongoengine"],
        "redis":      ["redis", "aioredis"],
        "sqlite":     ["sqlite3"],
    },
    "node": {
        "postgresql": ["pg", "@prisma/client", "knex"],
        "mysql":      ["mysql", "mysql2", "sequelize"],
        "mongodb":    ["mongoose", "mongodb"],
        "redis":      ["ioredis", "redis"],
    },
}

_ORM_SIGNALS: dict[str, str] = {
    "sqlalchemy":  "sqlalchemy",
    "django-orm":  "django",
    "prisma":      "prisma",
    "sequelize":   "sequelize",
    "mongoose":    "mongoose",
    "gorm":        "gorm",
}

_ENTRY_CANDIDATES: dict[str, list[str]] = {
    "python":     ["main.py", "app.py", "server.py", "run.py", "manage.py"],
    "node":       ["index.js", "server.js", "app.js", "main.js", "src/index.js"],
    "typescript": ["src/index.ts", "index.ts", "src/main.ts", "main.ts", "src/app.ts"],
    "java":       ["src/main/java", "Application.java"],
    "go":         ["cmd/main.go", "main.go"],
    "ruby":       ["config.ru", "app.rb"],
    "rust":       ["src/main.rs", "src/lib.rs"],
    "php":        ["public/index.php", "index.php", "artisan"],
    "dotnet":     ["Program.cs", "Startup.cs"],
    "dart":       ["bin/main.dart", "lib/main.dart", "web/main.dart"],
    "static":     ["index.html"],
}

_RUNTIME_FILES: dict[str, str] = {
    ".python-version": "python",
    ".nvmrc":          "node",
    ".node-version":   "node",
}

_STATIC_DIRS = ["public", "dist", "static", "build", "assets"]

_MEMORY_MAP = {
    "python":     {"256MB": ["flask"], "512MB": ["fastapi", "django"], "1GB": ["spring"]},
    "node":       {"256MB": ["express", "fastify"], "512MB": ["nextjs", "nuxt", "svelte"]},
    "typescript": {"256MB": ["express", "fastify"], "512MB": []},
    "java":       {"1GB": ["spring"]},
    "go":         {"256MB": [], "128MB": ["gin", "echo"]},
    "ruby":       {"512MB": ["rails"]},
    "rust":       {"128MB": [], "256MB": ["actix-web", "axum", "rocket", "warp"]},
    "php":        {"256MB": ["symfony"], "512MB": ["laravel"], "128MB": ["wordpress"]},
    "dotnet":     {"512MB": ["aspnetcore"], "256MB": ["blazor"]},
    "dart":       {"256MB": ["shelf"], "512MB": ["flutter"]},
    "static":     {"64MB": []},
}

_TARGET_ORDER = ["docker", "docker-compose", "ecs-fargate", "kubernetes", "ec2", "lambda"]


# ── Public API ────────────────────────────────────────────────────────────────

def scan(root: Path) -> DeployProfile:
    """Scan *root* directory and return a :class:`DeployProfile`.
    
    This is DETERMINISTIC rule-based detection. It follows clear patterns
    and signal detection. When multiple equally valid answers exist
    (Condition 1: Ambiguity), the ambiguity flags are set and AI can
    be used via `zonny deploy refine` to disambiguate.

    Parameters
    ----------
    root:
        Absolute path to the project root directory.

    Returns
    -------
    DeployProfile
        Fully populated profile with ambiguity tracking. If ambiguity.needs_ai
        is True, run `zonny deploy refine` (requires zonny-ai) to disambiguate.
    """
    from zonny_core.deploy.profile import AmbiguityFlags  # noqa: PLC0415
    
    root = root.resolve()
    all_text = _read_source_text(root)

    language   = _detect_language(root)
    runtime    = _detect_runtime(root, language)
    
    # NEW: Detect ambiguity (Condition 1)
    framework, all_frameworks = _detect_framework(all_text)
    entry, all_entries = _detect_entry_point(root, language)
    port, all_ports = _detect_port(all_text, language, framework)
    
    # Populate ambiguity flags
    ambiguity = AmbiguityFlags()
    
    if len(all_frameworks) > 1:
        ambiguity.multiple_frameworks = all_frameworks
        ambiguity.needs_ai = True
    
    if len(all_entries) > 1:
        ambiguity.multiple_entry_points = all_entries
        ambiguity.needs_ai = True
    
    if len(all_ports) > 1:
        ambiguity.conflicting_ports = all_ports
        ambiguity.needs_ai = True
    
    # If framework detection is weak, mark as uncertain
    if framework != "none" and all_text.count(framework) < 3:
        ambiguity.uncertain_framework = True
    
    build_cmd  = _detect_build_cmd(root, language)
    start_cmd  = _detect_start_cmd(language, framework, entry, port)
    databases  = _detect_databases(root, language, all_text)
    env_vars   = _detect_env_vars(root, all_text)
    has_static = _detect_static(root)
    memory     = _estimate_memory(language, framework)
    targets    = _rank_targets(language, framework, databases)

    # Phase 2: service type + monorepo
    service_type = _detect_service_type(root, language, framework, all_text, port)
    services: list[DeployProfile] = []
    if service_type == "multi":
        services = _detect_monorepo_services(root)

    return DeployProfile(
        project=root.name,
        language=language,
        runtime=runtime,
        framework=framework,
        entry_point=entry,
        port=port,
        build_cmd=build_cmd,
        start_cmd=start_cmd,
        databases=databases,
        env_vars=env_vars,
        has_static=has_static,
        estimated_memory=memory,
        deploy_targets=targets,
        ambiguity=ambiguity,
        ai_refined=False,
        service_type=service_type,
        services=services,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _read_source_text(root: Path, max_files: int = 50, max_bytes: int = 200_000) -> str:
    """Read a representative sample of the source into one big string."""
    parts: list[str] = []
    total = 0
    for ext in (".py", ".js", ".ts", ".java", ".go", ".rb", ".rs", ".php", ".cs", ".dart"):
        for f in root.rglob(f"*{ext}"):
            if any(skip in f.parts for skip in (
                "node_modules", ".git", "__pycache__", ".venv", "dist", "target",
                "vendor", ".dart_tool", "obj", "bin",
            )):
                continue
            try:
                chunk = f.read_text(encoding="utf-8", errors="ignore")[:4000]
                parts.append(chunk)
                total += len(chunk)
                if total >= max_bytes or len(parts) >= max_files:
                    break
            except OSError:
                continue
    # Also include dependency manifests
    for manifest in (
        "requirements.txt", "package.json", "pom.xml", "go.mod", "Gemfile",
        "Cargo.toml", "composer.json", "pubspec.yaml",
    ):
        p = root / manifest
        if p.exists():
            parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def _detect_language(root: Path) -> str:
    # TypeScript standalone: tsconfig.json + package.json (wins over plain node)
    if (root / "tsconfig.json").exists() and (root / "package.json").exists():
        return "typescript"

    for lang, signals in _LANG_SIGNALS.items():
        for sig in signals:
            if (root / sig).exists():
                return lang

    # .NET: variable filename (*.csproj / *.sln) — can't use static signal table
    if list(root.glob("*.csproj")) or list(root.glob("*.sln")) or (root / "global.json").exists():
        return "dotnet"

    # Static site: index.html with no backend signal detected above
    if (root / "index.html").exists():
        return "static"

    return "unknown"


def _detect_runtime(root: Path, language: str) -> str:
    # Check version pin files
    for fname, lang in _RUNTIME_FILES.items():
        fp = root / fname
        if fp.exists() and lang == language:
            ver = fp.read_text().strip().lstrip("v")
            return ver[:4]  # e.g. "3.11" or "20"

    if language == "python":
        pp = root / "pyproject.toml"
        if pp.exists():
            txt = pp.read_text()
            m = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', txt)
            if m:
                return m.group(1)
        return "3.11"
    if language == "node":
        pj = root / "package.json"
        if pj.exists():
            import json
            try:
                data = json.loads(pj.read_text())
                engines = data.get("engines", {}).get("node", "")
                m = re.search(r"(\d+)", engines)
                if m:
                    return m.group(1)
            except Exception:  # noqa: BLE001
                pass
        return "20"
    if language == "java":
        return "17"
    if language == "go":
        gm = root / "go.mod"
        if gm.exists():
            m = re.search(r"^go\s+(\d+\.\d+)", gm.read_text(), re.MULTILINE)
            if m:
                return m.group(1)
        return "1.22"
    if language == "ruby":
        rv = root / ".ruby-version"
        if rv.exists():
            return rv.read_text().strip().lstrip("ruby-")
        return "3.3"
    if language == "rust":
        cargo = root / "Cargo.toml"
        if cargo.exists():
            m = re.search(r'edition\s*=\s*"(\d+)"', cargo.read_text())
            if m:
                return m.group(1)  # e.g. "2021"
        return "stable"
    if language == "php":
        comp = root / "composer.json"
        if comp.exists():
            import json  # noqa: PLC0415
            try:
                data = json.loads(comp.read_text())
                ver = data.get("require", {}).get("php", "")
                m = re.search(r"([\d.]+)", ver)
                if m:
                    return m.group(1)
            except Exception:  # noqa: BLE001
                pass
        return "8.3"
    if language == "dotnet":
        csproj_files = list(root.glob("*.csproj"))
        if csproj_files:
            txt = csproj_files[0].read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"<TargetFramework>net([\d.]+)<", txt)
            if m:
                return m.group(1)  # e.g. "8.0"
        return "8.0"
    if language == "dart":
        pubspec = root / "pubspec.yaml"
        if pubspec.exists():
            txt = pubspec.read_text()
            m = re.search(r"sdk:\s*['\"]?>=([^\s'\"]+)", txt)
            if m:
                return m.group(1)
        return "3.0"
    if language in ("node", "typescript"):
        pj = root / "package.json"
        if pj.exists():
            import json  # noqa: PLC0415
            try:
                data = json.loads(pj.read_text())
                engines = data.get("engines", {}).get("node", "")
                mv = re.search(r"(\d+)", engines)
                if mv:
                    return mv.group(1)
            except Exception:  # noqa: BLE001
                pass
        return "20"
    if language == "static":
        return "nginx"
    return "unknown"


def _detect_framework(text: str) -> tuple[str, list[str]]:
    """Detect framework, returning (primary, all_matches).
    
    Returns:
        Tuple of (chosen_framework, list_of_all_detected_frameworks)
        
    If multiple frameworks are detected, this is AMBIGUITY (Condition 1)
    and AI should disambiguate via `zonny deploy refine`.
    """
    matches = []
    for fw, patterns in _FRAMEWORK_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                matches.append(fw)
                break  # One match per framework is enough
    
    # Return first match as primary, but track all
    primary = matches[0] if matches else "none"
    return primary, matches


def _detect_entry_point(root: Path, language: str) -> tuple[str, list[str]]:
    """Detect entry point, returning (primary, all_candidates).
    
    Multiple valid entry points = AMBIGUITY (Condition 1).
    AI can examine which one is actually imported/called.
    """
    candidates = _ENTRY_CANDIDATES.get(language, [])
    found = [c for c in candidates if (root / c).exists()]
    
    # Return first found as primary, all found as candidates
    primary = found[0] if found else ""
    return primary, found


def _detect_port(text: str, language: str, framework: str) -> tuple[int, list[int]]:
    """Detect port, returning (primary, all_detected_ports).
    
    Multiple different port numbers = AMBIGUITY (Condition 1).
    Which one is actually used? AI can check app.listen() vs environment vars.
    """
    found_ports = []
    for pat in _PORT_PATTERNS:
        for m in re.finditer(pat, text):
            try:
                port = int(m.group(1))
                if 1000 <= port <= 65535:  # Valid port range
                    found_ports.append(port)
            except (IndexError, ValueError):
                pass
    
    # Deduplicate while preserving order
    unique_ports = list(dict.fromkeys(found_ports))
    
    if unique_ports:
        primary = unique_ports[0]
    else:
        # Framework defaults
        defaults = {"fastapi": 8000, "flask": 5000, "django": 8000, "express": 3000,
                    "fastify": 3000, "spring": 8080, "rails": 3000}
        primary = defaults.get(framework, 8080)
        unique_ports = [primary]
    
    return primary, unique_ports


def _detect_build_cmd(root: Path, language: str) -> str:
    if language == "python":
        if (root / "requirements.txt").exists():
            return "pip install -r requirements.txt"
        if (root / "pyproject.toml").exists():
            return "pip install ."
    if language in ("node", "typescript"):
        if (root / "package.json").exists():
            try:
                import json  # noqa: PLC0415
                data = json.loads((root / "package.json").read_text())
                scripts = data.get("scripts", {})
                if "build" in scripts:
                    return "npm install && npm run build"
            except Exception:  # noqa: BLE001
                pass
            return "npm install"
    if language == "java":
        if (root / "mvnw").exists():
            return "./mvnw package -DskipTests"
        if (root / "gradlew").exists():
            return "./gradlew build -x test"
    if language == "go":
        return "go build -o app ."
    if language == "ruby":
        return "bundle install"
    if language == "rust":
        return "cargo build --release"
    if language == "php":
        return "composer install --no-dev --optimize-autoloader"
    if language == "dotnet":
        return "dotnet publish -c Release -o out"
    if language == "dart":
        pubspec = root / "pubspec.yaml"
        if pubspec.exists() and "flutter" in pubspec.read_text(encoding="utf-8", errors="ignore"):
            return "flutter build web"
        return "dart compile exe bin/main.dart -o bin/app"
    if language == "static":
        return ""  # no build step needed
    return ""


def _detect_start_cmd(language: str, framework: str, entry: str, port: int) -> str:
    if language == "python":
        if framework in ("fastapi", "flask"):
            mod = entry.replace(".py", "").replace("/", ".")
            return f"uvicorn {mod}:app --host 0.0.0.0 --port {port}"
        if framework == "django":
            return f"gunicorn wsgi:application --bind 0.0.0.0:{port}"
        return f"python {entry}"
    if language in ("node", "typescript"):
        if framework == "nextjs":
            return "npm start"
        if language == "typescript":
            ent_js = (entry or "src/index.ts").replace(".ts", ".js")
            return f"node dist/{ent_js.split('/')[-1]}"
        return f"node {entry}"
    if language == "java":
        return "java -jar app.jar"
    if language == "go":
        return "./app"
    if language == "ruby":
        return f"bundle exec rails server -p {port}" if framework == "rails" else f"bundle exec ruby {entry}"
    if language == "rust":
        proj_name = entry.split("/")[0] if "/" in entry else "app"
        return f"./target/release/{proj_name}"
    if language == "php":
        if framework == "laravel":
            return f"php artisan serve --host 0.0.0.0 --port {port}"
        if framework == "symfony":
            return f"php -S 0.0.0.0:{port} public/index.php"
        return f"php -S 0.0.0.0:{port} {entry or 'index.php'}"
    if language == "dotnet":
        return "dotnet out/app.dll"
    if language == "dart":
        if framework == "flutter":
            return "flutter run --release"
        return f"dart run {entry or 'bin/main.dart'}"
    if language == "static":
        return f"npx serve . -p {port}"
    return "./start.sh"


def _detect_databases(root: Path, language: str, text: str) -> list[DBDependency]:
    found: list[DBDependency] = []
    sigs = _DB_SIGNALS.get(language, {})
    for db_type, keywords in sigs.items():
        if any(kw.lower() in text.lower() for kw in keywords):
            # Detect ORM
            orm = "none"
            for orm_name, orm_kw in _ORM_SIGNALS.items():
                if orm_kw.lower() in text.lower():
                    orm = orm_name
                    break
            found.append(DBDependency(type=db_type, orm=orm))
    return found


def _detect_env_vars(root: Path, text: str) -> list[str]:
    """Collect environment variable names referenced in source code."""
    patterns = [
        r'os\.getenv\(["\']([A-Z_]{2,})["\']',      # Python
        r'os\.environ\[["\']([A-Z_]{2,})["\']',      # Python
        r'process\.env\.([A-Z_]{2,})',                # Node.js
        r'System\.getenv\("([A-Z_]{2,})"\)',          # Java
        r'os\.Getenv\("([A-Z_]{2,})"\)',              # Go
        r'ENV\[.([A-Z_]{2,}).\]',                    # Ruby
    ]
    names: set[str] = set()
    for pat in patterns:
        names.update(re.findall(pat, text))

    # Also read .env.example if present
    env_example = root / ".env.example"
    if env_example.exists():
        for line in env_example.read_text().splitlines():
            m = re.match(r'^([A-Z_]{2,})\s*=', line.strip())
            if m:
                names.add(m.group(1))

    return sorted(names)


def _detect_static(root: Path) -> bool:
    return any((root / d).is_dir() for d in _STATIC_DIRS)


def _estimate_memory(language: str, framework: str) -> str:
    mem_map = _MEMORY_MAP.get(language, {})
    for size, frameworks in sorted(mem_map.items(), key=lambda x: x[0]):
        if not frameworks or framework in frameworks:
            return size
    return "512MB"


def _rank_targets(language: str, framework: str, databases: list[DBDependency]) -> list[str]:
    targets = list(_TARGET_ORDER)
    if databases:
        # Compose is ideal when there are DB dependencies
        targets.remove("docker-compose")
        targets.insert(0, "docker-compose")
    if language == "go":
        # Go is a good Lambda fit (fast cold start, single binary)
        targets.remove("lambda")
        targets.insert(1, "lambda")
    if language == "rust":
        # Rust single binary: great for lambda, also lightweight docker
        targets.remove("lambda")
        targets.insert(1, "lambda")
    if language == "static":
        # Static sites only need a CDN/nginx — strip runtime targets
        return ["docker", "ec2"]
    if language == "dotnet":
        # .NET works on ECS/kubernetes, not typically lambda without extra work
        if "lambda" in targets:
            targets.remove("lambda")
    if framework in ("nextjs", "nuxt", "svelte", "flutter"):
        # SPA/SSR frameworks don't fit Lambda easily
        if "lambda" in targets:
            targets.remove("lambda")
    return targets

# ── Phase 2: service type + monorepo helpers ─────────────────────────────────

_HTTP_FRAMEWORKS = frozenset({
    "fastapi", "flask", "django", "express", "fastify", "nextjs",
    "nuxt", "svelte", "spring", "gin", "echo", "rails",
    "actix-web", "axum", "rocket", "warp",
    "laravel", "symfony", "aspnetcore", "blazor", "shelf",
})


def _detect_service_type(
    root: Path, language: str, framework: str, text: str, port: int
) -> str:
    """Return 'web' | 'worker' | 'static' | 'cron' | 'multi'."""
    # Monorepo wins first
    if _is_monorepo(root, language):
        return "multi"

    # Pure static site
    if language == "static":
        return "static"

    # Cron jobs (checked before worker because cron > worker priority)
    for pat in _CRON_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return "cron"

    # Background workers (only if no HTTP server framework)
    if framework not in _HTTP_FRAMEWORKS and framework != "none":
        pass  # has a framework we don't recognise as HTTP — default to web
    else:
        for pat in _WORKER_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                if framework not in _HTTP_FRAMEWORKS:
                    return "worker"

    return "web"


def _is_monorepo(root: Path, language: str) -> bool:  # noqa: ARG001
    """Return True when >=2 sub-directories each contain an app manifest.

    Intentionally language-agnostic: detects monorepos even when the root
    directory itself has no manifest (bare monorepo root with sub-packages).
    """
    _ALL_MANIFESTS = [
        "package.json", "pyproject.toml", "Cargo.toml",
        "composer.json", "pubspec.yaml", "go.mod", "Gemfile",
    ]
    _SKIP = {"node_modules", ".git", "__pycache__", ".venv", "dist", "build", "target"}

    def _has_app_manifest(d: Path) -> bool:
        return (
            any((d / m).exists() for m in _ALL_MANIFESTS)
            or bool(list(d.glob("*.csproj")))
        )

    count = sum(
        1
        for d in root.iterdir()
        if d.is_dir() and d.name not in _SKIP and not d.name.startswith(".")
        and _has_app_manifest(d)
    )
    return count >= 2


def _detect_monorepo_services(root: Path) -> list[DeployProfile]:
    """Scan each top-level sub-directory that looks like an independent app."""
    _SKIP = {"node_modules", ".git", "__pycache__", ".venv", "dist", "build", "target"}
    services: list[DeployProfile] = []
    for subdir in sorted(root.iterdir()):
        if not subdir.is_dir():
            continue
        if subdir.name.startswith(".") or subdir.name in _SKIP:
            continue
        # Must have at least one language signal to qualify as a service
        has_signal = (
            any(
                (subdir / sig).exists()
                for signals in _LANG_SIGNALS.values()
                for sig in signals
            )
            or bool(list(subdir.glob("*.csproj")))
            or (subdir / "index.html").exists()
        )
        if has_signal:
            try:
                services.append(scan(subdir))
            except Exception:  # noqa: BLE001
                pass
    return services