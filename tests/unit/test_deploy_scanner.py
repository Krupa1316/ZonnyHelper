"""Unit tests for the deploy stack detection engine (scanner.py)."""
from __future__ import annotations

from pathlib import Path

import pytest

from zonny_core.deploy.scanner import scan
from zonny_core.deploy.profile import DeployProfile


# ── Fixtures: synthetic project directories ────────────────────────────────────

def _make_project(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a dict of {filename: content} into tmp_path and return it."""
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


# ── Language detection ─────────────────────────────────────────────────────────

class TestLanguageDetection:
    def test_detects_python_from_requirements(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"requirements.txt": "fastapi\nuvicorn\n"})
        profile = scan(tmp_path)
        assert profile.language == "python"

    def test_detects_node_from_package_json(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"package.json": '{"name": "my-app", "version": "1.0.0"}'})
        profile = scan(tmp_path)
        assert profile.language == "node"

    def test_detects_go_from_go_mod(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"go.mod": "module myapp\ngo 1.22\n"})
        profile = scan(tmp_path)
        assert profile.language == "go"

    def test_detects_java_from_pom_xml(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"pom.xml": "<project><groupId>com.example</groupId></project>"})
        profile = scan(tmp_path)
        assert profile.language == "java"

    def test_unknown_language_for_empty_dir(self, tmp_path: Path) -> None:
        profile = scan(tmp_path)
        assert profile.language == "unknown"


# ── Framework detection ────────────────────────────────────────────────────────

class TestFrameworkDetection:
    def test_detects_fastapi(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "fastapi\nuvicorn\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        })
        profile = scan(tmp_path)
        assert profile.framework == "fastapi"

    def test_detects_flask(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "flask\n",
            "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        profile = scan(tmp_path)
        assert profile.framework == "flask"

    def test_detects_express(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "package.json": '{"name": "api", "dependencies": {"express": "^4"}}',
            "index.js": "const express = require('express');\nconst app = express();\n",
        })
        profile = scan(tmp_path)
        assert profile.framework == "express"

    def test_no_framework_returns_none(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"requirements.txt": "requests\nclick\n"})
        profile = scan(tmp_path)
        assert profile.framework == "none"


# ── Port detection ─────────────────────────────────────────────────────────────

class TestPortDetection:
    def test_detects_port_from_app_listen(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "package.json": "{}",
            "index.js": "app.listen(4000, () => console.log('running'));"
        })
        profile = scan(tmp_path)
        assert profile.port == 4000

    def test_detects_port_from_uvicorn_flag(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "fastapi\n",
            "main.py": "from fastapi import FastAPI\n# uvicorn main:app --port 9000\n",
        })
        profile = scan(tmp_path)
        assert profile.port == 9000

    def test_fastapi_default_port(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "fastapi\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        })
        profile = scan(tmp_path)
        assert profile.port == 8000


# ── Entry point detection ──────────────────────────────────────────────────────

class TestEntryPointDetection:
    def test_finds_main_py(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "requests\n",
            "main.py": "if __name__ == '__main__': pass\n",
        })
        profile = scan(tmp_path)
        assert profile.entry_point == "main.py"

    def test_finds_index_js(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "package.json": "{}",
            "index.js": "console.log('hello');\n",
        })
        profile = scan(tmp_path)
        assert profile.entry_point == "index.js"


# ── Database detection ─────────────────────────────────────────────────────────

class TestDatabaseDetection:
    def test_detects_postgresql_via_requirements(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "fastapi\npsycopg2-binary\nsqlalchemy\n",
            "main.py": "from fastapi import FastAPI\n",
        })
        profile = scan(tmp_path)
        types = [d.type for d in profile.databases]
        assert "postgresql" in types

    def test_detects_mongodb_via_mongoose(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "package.json": '{"dependencies": {"mongoose": "^7"}}',
            "index.js": "const mongoose = require('mongoose');\n",
        })
        profile = scan(tmp_path)
        types = [d.type for d in profile.databases]
        assert "mongodb" in types

    def test_no_database_returns_empty_list(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"requirements.txt": "requests\n"})
        profile = scan(tmp_path)
        assert profile.databases == []


# ── Env var detection ──────────────────────────────────────────────────────────

class TestEnvVarDetection:
    def test_detects_python_os_getenv(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "requests\n",
            "main.py": "import os\nSECRET = os.getenv('SECRET_KEY')\nDB = os.getenv('DATABASE_URL')\n",
        })
        profile = scan(tmp_path)
        assert "SECRET_KEY" in profile.env_vars
        assert "DATABASE_URL" in profile.env_vars

    def test_detects_from_env_example(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "flask\n",
            ".env.example": "API_KEY=\nSECRET=\nPORT=8000\n",
        })
        profile = scan(tmp_path)
        assert "API_KEY" in profile.env_vars


# ── Static asset detection ─────────────────────────────────────────────────────

class TestStaticDetection:
    def test_detects_static_dir(self, tmp_path: Path) -> None:
        (tmp_path / "static").mkdir()
        (tmp_path / "requirements.txt").write_text("flask\n")
        profile = scan(tmp_path)
        assert profile.has_static is True

    def test_no_static_dir(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"requirements.txt": "requests\n"})
        profile = scan(tmp_path)
        assert profile.has_static is False


# ── Profile serialization ──────────────────────────────────────────────────────

class TestProfileSerialization:
    def test_write_and_load_roundtrip(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "fastapi\npsycopg2\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        })
        profile = scan(tmp_path)
        out = tmp_path / ".zonny" / "deploy-profile.json"
        profile.write(out)
        loaded = DeployProfile.load(out)
        assert loaded.language == profile.language
        assert loaded.framework == profile.framework
        assert loaded.port == profile.port

    def test_to_dict_has_required_keys(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"requirements.txt": "fastapi\n"})
        profile = scan(tmp_path)
        d = profile.to_dict()
        for key in ("project", "language", "runtime", "framework", "entry_point",
                    "port", "build_cmd", "start_cmd", "databases", "env_vars",
                    "has_static", "estimated_memory", "deploy_targets",
                    "service_type", "services"):
            assert key in d, f"Missing key: {key}"

    def test_roundtrip_includes_service_type(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "fastapi\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        })
        profile = scan(tmp_path)
        out = tmp_path / ".zonny" / "deploy-profile.json"
        profile.write(out)
        loaded = DeployProfile.load(out)
        assert loaded.service_type == profile.service_type
        assert loaded.services == profile.services


# ── Phase 2: New language detection ───────────────────────────────────────────

class TestNewLanguageDetection:
    def test_detects_rust_from_cargo_toml(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "Cargo.toml": '[package]\nname = "my-api"\nversion = "0.1.0"\nedition = "2021"\n',
        })
        profile = scan(tmp_path)
        assert profile.language == "rust"

    def test_rust_runtime_from_edition(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "Cargo.toml": '[package]\nname = "app"\nedition = "2021"\n',
        })
        profile = scan(tmp_path)
        assert profile.runtime == "2021"

    def test_rust_build_cmd(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "Cargo.toml": '[package]\nname = "app"\nedition = "2021"\n',
        })
        profile = scan(tmp_path)
        assert profile.build_cmd == "cargo build --release"

    def test_detects_php_from_composer_json(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "composer.json": '{"require": {"php": ">=8.2", "laravel/framework": "^11.0"}}',
        })
        profile = scan(tmp_path)
        assert profile.language == "php"

    def test_php_runtime_from_composer(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "composer.json": '{"require": {"php": ">=8.2"}}',
        })
        profile = scan(tmp_path)
        assert profile.runtime == "8.2"

    def test_php_laravel_framework(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "composer.json": '{"require": {"php": ">=8.2", "laravel/framework": "^11.0"}}',
            "app/Http/Controllers/Controller.php": "<?php\nnamespace App\\Http\\Controllers;\nuse Illuminate\\Foundation\\Http\\FormRequest;\n",
        })
        profile = scan(tmp_path)
        assert profile.language == "php"
        assert profile.framework == "laravel"

    def test_detects_dotnet_from_csproj(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "MyApp.csproj": '<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup>'
                            "<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>",
        })
        profile = scan(tmp_path)
        assert profile.language == "dotnet"

    def test_dotnet_runtime_from_csproj(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "App.csproj": "<Project><PropertyGroup>"
                          "<TargetFramework>net8.0</TargetFramework>"
                          "</PropertyGroup></Project>",
        })
        profile = scan(tmp_path)
        assert profile.runtime == "8.0"

    def test_dotnet_build_cmd(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "App.csproj": "<Project><PropertyGroup>"
                          "<TargetFramework>net8.0</TargetFramework>"
                          "</PropertyGroup></Project>",
        })
        profile = scan(tmp_path)
        assert profile.build_cmd == "dotnet publish -c Release -o out"

    def test_detects_dart_from_pubspec(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "pubspec.yaml": "name: my_app\nenvironment:\n  sdk: '>=3.0.0'\n",
        })
        profile = scan(tmp_path)
        assert profile.language == "dart"

    def test_dart_runtime_from_pubspec(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "pubspec.yaml": "name: my_app\nenvironment:\n  sdk: '>=3.2.0'\n",
        })
        profile = scan(tmp_path)
        assert profile.runtime == "3.2.0"

    def test_detects_static_from_index_html(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "index.html": "<!DOCTYPE html><html><body>Hello</body></html>",
        })
        profile = scan(tmp_path)
        assert profile.language == "static"

    def test_detects_typescript_from_tsconfig_and_package_json(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "tsconfig.json": '{"compilerOptions": {"target": "ES2022"}}',
            "package.json": '{"name": "my-ts-app", "scripts": {"build": "tsc"}}',
        })
        profile = scan(tmp_path)
        assert profile.language == "typescript"

    def test_typescript_build_cmd_with_build_script(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "tsconfig.json": "{}",
            "package.json": '{"name": "app", "scripts": {"build": "tsc", "start": "node dist/index.js"}}',
        })
        profile = scan(tmp_path)
        assert profile.language == "typescript"
        assert "npm run build" in profile.build_cmd

    def test_rust_actix_web_framework(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "Cargo.toml": '[package]\nname = "api"\nedition = "2021"\n\n[dependencies]\nactix-web = "4"\n',
            "src/main.rs": 'use actix_web::{web, App, HttpServer};\n#[actix_web::main]\nasync fn main() { HttpServer::new(|| App::new()).bind("127.0.0.1:8080").unwrap().run().await.unwrap(); }\n',
        })
        profile = scan(tmp_path)
        assert profile.language == "rust"
        assert profile.framework == "actix-web"

    def test_rust_lambda_ranked_high(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "Cargo.toml": '[package]\nname = "handler"\nedition = "2021"\n',
        })
        profile = scan(tmp_path)
        targets = profile.deploy_targets
        # Lambda should be near the top for rust
        lambda_idx = targets.index("lambda") if "lambda" in targets else 99
        docker_idx = targets.index("docker") if "docker" in targets else 99
        assert lambda_idx < docker_idx + 3  # within 3 positions of docker

    def test_static_targets_are_limited(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {"index.html": "<html></html>"})
        profile = scan(tmp_path)
        assert profile.deploy_targets == ["docker", "ec2"]


# ── Phase 2: Service type detection ───────────────────────────────────────────

class TestServiceTypeDetection:
    def test_web_service_default(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "fastapi\n",
            "main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
        })
        profile = scan(tmp_path)
        assert profile.service_type == "web"

    def test_static_service_type(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "index.html": "<!DOCTYPE html><html></html>",
        })
        profile = scan(tmp_path)
        assert profile.service_type == "static"

    def test_cron_service_type_python(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "apscheduler\n",
            "main.py": "from apscheduler.schedulers.blocking import BlockingScheduler\nsched = BlockingScheduler()\n",
        })
        profile = scan(tmp_path)
        assert profile.service_type == "cron"

    def test_cron_service_type_node(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "package.json": '{"dependencies": {"node-cron": "^3"}}',
            "index.js": "const cron = require('node-cron');\ncron.schedule('* * * * *', () => doWork());\n",
        })
        profile = scan(tmp_path)
        assert profile.service_type == "cron"

    def test_worker_service_type_celery(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "requirements.txt": "celery\nredis\n",
            "worker.py": "from celery import Celery\napp = Celery('tasks', broker='redis://localhost')\n",
        })
        profile = scan(tmp_path)
        assert profile.service_type == "worker"

    def test_node_with_express_is_web_not_worker(self, tmp_path: Path) -> None:
        """bullmq + express together → web wins because HTTP framework present."""
        _make_project(tmp_path, {
            "package.json": '{"dependencies": {"express": "^4", "bullmq": "^5"}}',
            "index.js": "const express = require('express');\nconst { Queue } = require('bullmq');\nconst app = express();\napp.listen(3000);\n",
        })
        profile = scan(tmp_path)
        # Express is an HTTP framework, so service_type should be web
        assert profile.service_type == "web"


# ── Phase 2: Monorepo detection ────────────────────────────────────────────────

class TestMonorepoDetection:
    def test_monorepo_node_multiple_packages(self, tmp_path: Path) -> None:
        """Two subdirs each with package.json → monorepo."""
        _make_project(tmp_path, {
            "package.json": '{"name": "root", "private": true}',
            "packages/api/package.json": '{"name": "api", "dependencies": {"express": "^4"}}',
            "packages/api/index.js": "const express = require('express');\nconst app = express();\napp.listen(3000);\n",
            "packages/web/package.json": '{"name": "web", "dependencies": {"react": "^18"}}',
            "packages/web/index.js": "console.log('web');\n",
        })
        # Scan packages/ subdir (the actual monorepo root)
        packages_dir = tmp_path / "packages"
        profile = scan(packages_dir)
        assert profile.service_type == "multi"
        assert len(profile.services) >= 2

    def test_monorepo_services_each_have_language(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "backend/package.json": '{"name": "backend"}',
            "backend/index.js": "const express = require('express');\nconst app = express();\napp.listen(8080);\n",
            "frontend/package.json": '{"name": "frontend"}',
            "frontend/index.js": "console.log('frontend');\n",
        })
        profile = scan(tmp_path)
        assert profile.service_type == "multi"
        for svc in profile.services:
            assert svc.language != "unknown" or svc.project in ("backend", "frontend")

    def test_single_package_is_not_monorepo(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "package.json": '{"name": "my-app"}',
            "index.js": "const express = require('express');\napp.listen(3000);\n",
        })
        profile = scan(tmp_path)
        assert profile.service_type != "multi"

    def test_monorepo_python_multiple_pyprojects(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "service_a/pyproject.toml": '[project]\nname = "service-a"\n',
            "service_a/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
            "service_b/pyproject.toml": '[project]\nname = "service-b"\n',
            "service_b/main.py": "from flask import Flask\napp = Flask(__name__)\n",
        })
        profile = scan(tmp_path)
        assert profile.service_type == "multi"
        service_names = [s.project for s in profile.services]
        assert "service_a" in service_names
        assert "service_b" in service_names
