import argparse
import asyncio
import os
import sys

from pathlib import Path

from utils import (
    ServiceManifestError,
    PluginManifestError,
    load_manifest,
    validate_manifest,
    load_valid_services,
    load_plugin_manifest,
    validate_plugin_manifest,
    load_valid_plugins,
    get_repo_root,
    get_service_path,
    get_plugin_path,
)
from generators.runner import run_service, run_infra, run_plugins, run_plugin, run_project
from migrations import get_migrations_manager


def cmd_init(args: argparse.Namespace) -> int:
    service_path = Path(args.path)
    name = service_path.name

    if not service_path.exists():
        service_path.mkdir(parents=True)

    service_yaml = service_path / "service.yaml"
    if service_yaml.exists():
        print(f"[codegen] {service_yaml} already exists — skipping.")
        return 0

    service_yaml.write_text(
        f"""\
service:
  name: {name}
  version: 0.1.0
  description: ""

  # Enable service in project generation
  active: false

  # Python version
  python:
    major: 3
    minor: 12

  # User main.py
  main:
    enabled: false

  # gRPC server
  grpc:
    enabled: false
    port: 8080

  # gRPC client (call other services)
  grpc_client:
    enabled: false
    services: []

  # Kafka
  kafka_producer:
    enabled: false
    topics: []

  kafka_consumer:
    enabled: false
    topics: []
    group_id: null
    auto_offset_reset: "earliest"
    max_poll_records: 100
    max_poll_interval_ms: 300000

  # Infrastructure
  postgres:
    enabled: false
    pool_size: 10
    pool_max_overflow: 5
    pool_mode: "transaction"
    migration_dir: "migrations"

  minio:
    enabled: false
    buckets: []

  vault:
    enabled: false
    vars: []

  scheduler:
    enabled: false
    storage: "memory"

  # Ticket Authorization
  ticket_auth:
    enabled: false
    tas_service: ""
    ticket_ttl: 60

  # Feature flags
  config:
    enabled: false

  logging:
    file:
        level: DEBUG
        path: logs/app.log
        max_bytes: 10485760  # 10MB
        backup_count: 5
    loki:
        enabled: false
        level: INFO
        batch_size: 100
        flush_interval: 5
        max_retries: 3
        timeout: 10

  # Observability
  observability:
    enabled: true
    log_level: INFO
    trace_sampling_rate: 1.0
    metrics_enabled: true
    service_name: null
""",
        encoding="utf-8",
    )

    src_dir = service_path / "src"
    if not src_dir.exists():
        src_dir.mkdir()

    (src_dir / "__init__.py").write_text("")

    tests_dir = service_path / "tests"
    if not tests_dir.exists():
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text(
            f"# pytest fixtures for {name}\nfrom generated.testing.fixtures import *  # noqa: F401, F403\n",
            encoding="utf-8",
        )
        (tests_dir / "test_service.py").write_text(
            "import pytest\nimport grpc\n\n\n@pytest.mark.asyncio\nasync def test_service_initialization(mock_context):\n    assert mock_context.code == grpc.StatusCode.OK\n",
            encoding="utf-8",
        )

    pytest_ini = service_path / "pytest.ini"
    if not pytest_ini.exists():
        pytest_ini.write_text(
            "[pytest]\ntestpaths = tests\npython_files = test_*.py\nasyncio_mode = auto\npythonpath = . generated src\n",
            encoding="utf-8",
        )

    print(f"[codegen] Initialized {service_path / 'service.yaml'}")
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    path = Path.cwd()

    try:
        warnings = validate_manifest(path)
    except ServiceManifestError as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    print(f"[codegen] {path} is valid")
    if warnings:
        for w in warnings:
            print(f"[codegen] WARNING: {w}")

    return 0


def cmd_service(args: argparse.Namespace) -> int:
    manifest_path = Path.cwd() / "service.yaml"
    output_path = Path.cwd() / "generated/"

    try:
        manifest = load_manifest(manifest_path)
    except ServiceManifestError as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    try:
        run_service(manifest, output_path, docker=args.docker)
    except Exception as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_infra(_: argparse.Namespace) -> int:
    try:
        services = load_valid_services()
        run_infra(services)
    except Exception as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_project(args: argparse.Namespace) -> int:
    try:
        services = load_valid_services()
        run_project(services, docker=args.docker)
    except Exception as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_plugin_init(args: argparse.Namespace) -> int:
    plugin_path = Path(args.path)
    name = plugin_path.name

    if not plugin_path.exists():
        plugin_path.mkdir(parents=True)

    plugin_yaml = plugin_path / "plugin.yaml"
    if plugin_yaml.exists():
        print(f"[codegen] {plugin_yaml} already exists — skipping.")
        return 0

    plugin_yaml.write_text(
        f"""\
plugin:
  name: {name}
  version: 0.1.0
  description: ""
  category: "general"
  language: python
  active: true

  # Streaming inputs and buffer rules
  inputs:
    - name: input_stream
      type: stream/binary
      required: true
      buffer:
        strategy: size
        chunk_size_bytes: 5242880
        time_window_ms: 10000
        delimiter: null
        overlap_bytes: 0

  # Streaming outputs and artifacts
  outputs:
    - name: output_stream
      type: stream/text
    - name: result_file
      type: artifact/file
      filename: "result.txt"

  # User parameters
  parameters:
    - name: example_param
      type: string
      default: "default_value"
      description: "Example parameter"

  # Platform permissions (zero secrets in container)
  permissions:
    llm:
      enabled: false
      allowed_purposes: []
      allowed_models: []
    storage:
      enabled: true
      upload_artifacts: true
    database:
      enabled: false
      allowed_entities: []
    network:
      egress: false
      allowed_hosts: []
""",
        encoding="utf-8",
    )

    src_dir = plugin_path / "src"
    if not src_dir.exists():
        src_dir.mkdir()

    (src_dir / "__init__.py").write_text("")
    (src_dir / "plugin.py").write_text(
        """from generated.models import PluginContext
from generated.sidecar_client import SidecarAgentClient


class PluginHandler:
    def __init__(self, context: PluginContext, sidecar: SidecarAgentClient) -> None:
        self.context = context
        self.sidecar = sidecar

    async def on_start(self) -> None:
        pass

    async def process_buffer(self, buffer: bytes) -> None:
        pass

    async def on_finish(self) -> None:
        pass
""",
        encoding="utf-8",
    )

    req_file = plugin_path / "requirements.txt"
    if not req_file.exists():
        req_file.write_text("# Plugin custom dependencies\n", encoding="utf-8")

    tests_dir = plugin_path / "tests"
    if not tests_dir.exists():
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text("# pytest fixtures for plugin\n", encoding="utf-8")
        (tests_dir / "test_plugin.py").write_text(
            """import pytest


@pytest.mark.asyncio
async def test_plugin_structure():
    assert True
""",
            encoding="utf-8",
        )

    pytest_ini = plugin_path / "pytest.ini"
    if not pytest_ini.exists():
        pytest_ini.write_text(
            "[pytest]\ntestpaths = tests\npython_files = test_*.py\nasyncio_mode = auto\npythonpath = . generated src\n",
            encoding="utf-8",
        )

    print(f"[codegen] Initialized {plugin_path / 'plugin.yaml'}")
    return 0


def cmd_plugin_validate(args: argparse.Namespace) -> int:
    path = Path(getattr(args, "path", ".")).resolve()
    if path.is_dir() and (path / "plugin.yaml").exists():
        path = path / "plugin.yaml"

    try:
        warnings = validate_plugin_manifest(path)
    except PluginManifestError as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    print(f"[codegen] {path} is valid")
    if warnings:
        for w in warnings:
            print(f"[codegen] WARNING: {w}")

    return 0


def cmd_plugin_generate(args: argparse.Namespace) -> int:
    plugin_name = getattr(args, "plugin_name", None)
    if plugin_name:
        try:
            plugin_path = get_plugin_path(plugin_name)
            manifest = load_plugin_manifest(plugin_path / "plugin.yaml")
            run_plugin(manifest, plugin_path / "generated/", docker=getattr(args, "docker", False))
            return 0
        except Exception as e:
            print(f"[codegen] ERROR: {e}", file=sys.stderr)
            return 1

    manifest_path = Path.cwd() / "plugin.yaml"
    output_path = Path.cwd() / "generated/"

    try:
        manifest = load_plugin_manifest(manifest_path)
    except PluginManifestError as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    try:
        run_plugin(manifest, output_path, docker=getattr(args, "docker", False))
    except Exception as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_plugins(args: argparse.Namespace) -> int:
    try:
        plugin_name = getattr(args, "plugin_name", None)
        if plugin_name:
            plugin_path = get_plugin_path(plugin_name)
            manifest = load_plugin_manifest(plugin_path / "plugin.yaml")
            run_plugin(manifest, plugin_path / "generated/", docker=getattr(args, "docker", False))
        else:
            run_plugins(docker=getattr(args, "docker", False))
    except Exception as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_migrations_status(args: argparse.Namespace) -> int:
    service_root = Path(args.service_root or ".").resolve()
    manager = get_migrations_manager(service_root)
    result = asyncio.run(manager.status())
    migrations_dir = result["migrations_dir"]

    print("–" * 70)

    print(f"Migrations directory: {migrations_dir}")
    print(f"{'Seq':>4}  {'Status':<8}  Name")
    print("-" * 60)

    for m in result["migrations"]:
        status = "APPLIED" if m["applied"] else "PENDING"
        print(f"{m['sequence']:>4}  {status:<8}  {m['name']}")

    return 0


def cmd_migrations_migrate(args: argparse.Namespace) -> int:
    service_root = Path(args.service_root or ".").resolve()
    manager = get_migrations_manager(service_root)
    result = asyncio.run(manager.migrate())

    print("–" * 70)

    if result["applied"]:
        print(f"Applied: {', '.join(result['applied'])}")

    if result["skipped"]:
        print(f"Skipped (already applied): {', '.join(result['skipped'])}")

    if result["errors"]:
        for e in result["errors"]:
            print(f"ERROR in {e['migration']}: {e['error']}", file=sys.stderr)

        return 1

    return 0


def cmd_migrations_rollback(args: argparse.Namespace) -> int:
    if args.steps < 1:
        print("ERROR: steps must be >= 1", file=sys.stderr)
        return 1

    service_root = Path(args.service_root or ".").resolve()
    manager = get_migrations_manager(service_root)
    result = asyncio.run(manager.rollback(steps=args.steps))

    print("–" * 70)

    if result.get("message"):
        print(result["message"])

    if result["rolled_back"]:
        print(f"Rolled back: {', '.join(result['rolled_back'])}")

    if result["errors"]:
        for e in result["errors"]:
            print(f"ERROR in {e['migration']}: {e['error']}", file=sys.stderr)
        return 1

    return 0


def cmd_migrations_make(args: argparse.Namespace) -> int:
    service_root = Path(args.service_root or ".").resolve()
    manager = get_migrations_manager(service_root)
    result = manager.make()

    print("–" * 70)

    if result.migration_file:
        print(f"Created migration: {result.migration_file}")

        if result.changes:
            print("Changes:")

            for change in result.changes:
                print(f"  {change}")
    
    if result.message:
        print(result.message)

    if result.error:
        print(f"ERROR: {result.error}", file=sys.stderr)

        return 1

    return 0


def cmd_test(args: argparse.Namespace) -> int:
    import subprocess

    repo_root = get_repo_root()
    service_name = getattr(args, "service_name", None)

    if service_name:
        try:
            svc_path = get_service_path(service_name)
        except Exception as e:
            print(f"[codegen] ERROR: {e}", file=sys.stderr)
            return 1

        tests_dir = svc_path / "tests"
        if not tests_dir.exists():
            print(f"[codegen] No tests directory found in {svc_path}")
            return 0

        print(f"[codegen] Running tests for {service_name}...")
        env = dict(os.environ)
        env["CODEGEN_ROOT"] = str(repo_root)
        res = subprocess.run([sys.executable, "-m", "pytest", "tests", "--import-mode=importlib", "-q"], cwd=str(svc_path), env=env)
        return res.returncode

    suites = []
    for category, filename, key in (("services", "service.yaml", "service"),
                                    ("plugins", "plugin.yaml", "plugin")):
        for path in sorted((repo_root / category).rglob(filename)):
            try:
                manifest = load_manifest(path) if key == "service" else load_plugin_manifest(path)
                active = getattr(manifest, key).active
            except (ServiceManifestError, PluginManifestError):
                continue
            if active and (path.parent / "tests").is_dir():
                suites.append(path.parent)
    total_code = 0
    for suite in suites:
        print(f"[codegen] Running tests for {suite.relative_to(repo_root)}", flush=True)
        env = dict(os.environ, CODEGEN_ROOT=str(repo_root))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "--import-mode=importlib", "-q"],
            cwd=suite, env=env,
        )
        if result.returncode not in (0, 5):
            total_code = result.returncode
    return total_code


def _dispatch_migration(args: argparse.Namespace) -> int:
    commands = {
        "status": cmd_migrations_status,
        "migrate": cmd_migrations_migrate,
        "rollback": cmd_migrations_rollback,
        "make": cmd_migrations_make,
    }

    return commands[args.command](args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codegen", description="codegen — code generator for Python microservices")
    sub = parser.add_subparsers(required=True)

    p_init = sub.add_parser("init", help="Scaffold a new service directory with service.yaml")
    p_init.add_argument("path", nargs="?", default=".")
    p_init.set_defaults(func=cmd_init)

    p_validate = sub.add_parser("validate", help="Validate a service.yaml file in current directory")
    p_validate.set_defaults(func=cmd_validate)

    p_gen = sub.add_parser("service", help="Generate code from service.yaml")
    p_gen.add_argument("--docker", action="store_true", help="Use Docker service names as addresses instead of localhost")
    p_gen.set_defaults(func=cmd_service)

    p_gen = sub.add_parser("infra", help="Generate init scripts for infra/")
    p_gen.set_defaults(func=cmd_infra)

    p_plugins = sub.add_parser("plugins", help="Generate code for plugins/ (all active or specific plugin)")
    p_plugins.add_argument("plugin_name", nargs="?", default=None, help="Optional plugin name")
    p_plugins.add_argument("--docker", action="store_true", help="Use Docker network addresses")
    p_plugins.set_defaults(func=cmd_plugins)

    # Sub-command: plugin
    p_plugin = sub.add_parser("plugin", help="Plugin management: init, validate, generate")
    p_plugin_sub = p_plugin.add_subparsers(required=True)

    p_pinit = p_plugin_sub.add_parser("init", help="Scaffold a new plugin directory with plugin.yaml")
    p_pinit.add_argument("path", help="Plugin directory path, e.g. plugins/media/speech_to_text")
    p_pinit.set_defaults(func=cmd_plugin_init)

    p_pval = p_plugin_sub.add_parser("validate", help="Validate plugin.yaml in current or target directory")
    p_pval.add_argument("path", nargs="?", default=".", help="Target path")
    p_pval.set_defaults(func=cmd_plugin_validate)

    p_pgen = p_plugin_sub.add_parser("generate", help="Generate code from plugin.yaml")
    p_pgen.add_argument("plugin_name", nargs="?", default=None, help="Optional plugin name")
    p_pgen.add_argument("--docker", action="store_true", help="Use Docker network addresses")
    p_pgen.set_defaults(func=cmd_plugin_generate)

    p_gen = sub.add_parser("project", help="generate all project files")
    p_gen.add_argument("--docker", action="store_true", help="Use Docker service names as addresses instead of localhost")
    p_gen.set_defaults(func=cmd_project)

    p_test = sub.add_parser("test", help="Run pytest for a service or all active services")
    p_test.add_argument("service_name", nargs="?", default=None, help="Optional service name")
    p_test.set_defaults(func=cmd_test)

    p_mig = sub.add_parser("migrations", help="Database migrations: make, migrate, status, rollback")
    p_mig.add_argument("command", choices=["make", "migrate", "status", "rollback"], help="Migration command")
    p_mig.add_argument("--service-root", default=".", help="Service root directory (default: current directory)")
    p_mig.add_argument("--db-url", default=None, help="PostgreSQL connection URL (overrides settings/env)")
    p_mig.add_argument("--steps", type=int, default=1, help="Number of migrations to rollback (default: 1)")
    p_mig.set_defaults(func=lambda args: _dispatch_migration(args))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
