"""Deploy profile data model.

The DeployProfile is the interface contract between zonny-core (writes it via
`zonny deploy scan`) and zonny-ai (reads it via `zonny deploy plan`).
It is also consumed by `zonny deploy generate` to produce config files.

Roadmap extension (see DEPLOYER_ROADMAP.md):
  - EnvProfile will be added in env_scanner.py to detect OS, installed tools,
    cloud context (EC2/GCP/Azure/local), and available resources.
  - AppProfile will gain `service_type` and `services[]` (monorepo support).
  - Together AppProfile + EnvProfile feed the AI DeploymentAdvisor which
    powers `zonny deploy auto` — a single command that scans, picks the best
    target, generates config, deploys, and health-checks automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

import json


@dataclass
class DBDependency:
    """A detected database dependency."""
    type: str    # postgresql | mysql | mongodb | redis | sqlite
    orm: str     # sqlalchemy | prisma | mongoose | jdbc | django-orm | none


@dataclass
class AmbiguityFlags:
    """Tracks what was ambiguous and requires AI disambiguation (Condition 1)."""
    multiple_frameworks: list[str] = field(default_factory=list)  # e.g., ["flask", "fastapi"]
    multiple_entry_points: list[str] = field(default_factory=list)
    conflicting_ports: list[int] = field(default_factory=list)
    uncertain_framework: bool = False
    needs_ai: bool = False  # True if any ambiguity exists


@dataclass
class DeployProfile:
    """Full auto-detected deployment profile for a project.
    
    This profile is created by DETERMINISTIC scanning rules first.
    If ambiguities are detected (Condition 1: multiple valid answers),
    the AI can refine it via `zonny deploy refine` (zonny-ai).
    """

    project: str                     # directory name
    language: str                    # python | node | java | go | ruby | unknown
    runtime: str                     # 3.11 | 20 | 17 | 1.22 | 3.3
    framework: str                   # fastapi | express | spring | gin | rails | django | none
    entry_point: str                 # main.py | index.js | cmd/main.go
    port: int                        # detected port number (default 8080)
    build_cmd: str                   # pip install -r requirements.txt | npm install
    start_cmd: str                   # uvicorn main:app --host 0.0.0.0 --port 8000
    databases: list[DBDependency] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    has_static: bool = False         # public/, dist/, static/ detected
    estimated_memory: str = "512MB"  # rough estimate for k8s/ECS sizing
    deploy_targets: list[str] = field(default_factory=list)
    
    # NEW: Ambiguity tracking (Condition 1)
    ambiguity: AmbiguityFlags = field(default_factory=AmbiguityFlags)
    ai_refined: bool = False  # True if AI has disambiguated this profile

    # Phase 2: service classification + monorepo support
    service_type: str = "web"               # "web" | "worker" | "static" | "cron" | "multi"
    services: list["DeployProfile"] = field(default_factory=list)  # non-empty for monorepos

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-serializable)."""
        return {
            "project": self.project,
            "language": self.language,
            "runtime": self.runtime,
            "framework": self.framework,
            "entry_point": self.entry_point,
            "port": self.port,
            "build_cmd": self.build_cmd,
            "start_cmd": self.start_cmd,
            "databases": [{"type": d.type, "orm": d.orm} for d in self.databases],
            "env_vars": self.env_vars,
            "has_static": self.has_static,
            "estimated_memory": self.estimated_memory,
            "deploy_targets": self.deploy_targets,
            "ambiguity": {
                "multiple_frameworks": self.ambiguity.multiple_frameworks,
                "multiple_entry_points": self.ambiguity.multiple_entry_points,
                "conflicting_ports": self.ambiguity.conflicting_ports,
                "uncertain_framework": self.ambiguity.uncertain_framework,
                "needs_ai": self.ambiguity.needs_ai,
            },
            "ai_refined": self.ai_refined,
            "service_type": self.service_type,
            "services": [s.to_dict() for s in self.services],
        }

    def write(self, path: Path) -> None:
        """Write profile as JSON to *path*."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "DeployProfile":
        """Reconstruct a DeployProfile from a plain dict (inverse of ``to_dict()``)."""
        dbs = [DBDependency(**d) for d in data.pop("databases", [])]
        ambig_data = data.pop("ambiguity", {})
        ambig = AmbiguityFlags(
            multiple_frameworks=ambig_data.get("multiple_frameworks", []),
            multiple_entry_points=ambig_data.get("multiple_entry_points", []),
            conflicting_ports=ambig_data.get("conflicting_ports", []),
            uncertain_framework=ambig_data.get("uncertain_framework", False),
            needs_ai=ambig_data.get("needs_ai", False),
        )
        ai_refined = data.pop("ai_refined", False)
        service_type = data.pop("service_type", "web")
        services_raw = data.pop("services", [])
        services = [cls._from_dict(s) for s in services_raw]
        return cls(
            **data,
            databases=dbs,
            ambiguity=ambig,
            ai_refined=ai_refined,
            service_type=service_type,
            services=services,
        )

    @classmethod
    def load(cls, path: Path) -> "DeployProfile":
        """Load a DeployProfile from a JSON file written by ``write()``."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls._from_dict(data)
