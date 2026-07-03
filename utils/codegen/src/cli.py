import argparse
import asyncio
import sys

from pathlib import Path

from utils import ServiceManifestError, load_manifest, validate_manifest
from generators.runner import run_all
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

  # User main
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

#   # Kafka
#   kafka_producer:
#     enabled: false
#     topics: []

#   kafka_consumer:
#     enabled: false
#     topics: []

  # Infrastructure
  postgres:
    enabled: false
    pool_size: 10
    pool_max_overflow: 5
    pool_mode: "transaction"
    migration_dir: "migrations"

#   minio:
#     enabled: false
#     buckets: []

#   vault:
#     enabled: true

#   # Auth (ticket-based inter-service auth)
#   auth:
#     enabled: true

#   # Feature flags client
#   config_client:
#     enabled: false
#     flags: []

#   # Observability
#   observability:
#     enabled: true
#     log_level: INFO
#     trace_sampling_rate: 1.0
#     metrics_enabled: true
""",
        encoding="utf-8",
    )

    src_dir = service_path / "src"
    if not src_dir.exists():
        src_dir.mkdir()

    (src_dir / "__init__.py").write_text("")

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


def cmd_generate(args: argparse.Namespace) -> int:
    manifest_path = Path.cwd() / "service.yaml"
    output_path = Path.cwd() / "generated/"

    try:
        manifest = load_manifest(manifest_path)
    except ServiceManifestError as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    try:
        run_all(manifest, output_path, watch=args.watch)
    except Exception as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_migrations_status(args: argparse.Namespace) -> int:
    service_root = Path(args.service_root or ".").resolve()
    manager = get_migrations_manager(service_root, db_url=args.db_url)
    result = asyncio.run(manager.status())
    migrations_dir = result["migrations_dir"]

    print(f"Migrations directory: {migrations_dir}")
    print(f"{'Seq':>4}  {'Status':<8}  Name")
    print("-" * 60)

    for m in result["migrations"]:
        status = "APPLIED" if m["applied"] else "PENDING"
        print(f"{m['sequence']:>4}  {status:<8}  {m['name']}")

    return 0


def cmd_migrations_migrate(args: argparse.Namespace) -> int:
    service_root = Path(args.service_root or ".").resolve()
    manager = get_migrations_manager(service_root, db_url=args.db_url)
    result = asyncio.run(manager.migrate())

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
    service_root = Path(args.service_root or ".").resolve()
    manager = get_migrations_manager(service_root, db_url=args.db_url)
    result = asyncio.run(manager.rollback(steps=args.steps))

    if result["rolled_back"]:
        print(f"Rolled back: {', '.join(result['rolled_back'])}")

    if result["errors"]:
        for e in result["errors"]:
            print(f"ERROR in {e['migration']}: {e['error']}", file=sys.stderr)

        return 1

    return 0


def cmd_migrations_make(args: argparse.Namespace) -> int:
    service_root = Path(args.service_root or ".").resolve()
    manager = get_migrations_manager(service_root, db_url=args.db_url)
    result = asyncio.run(manager.make())

    if result.get("migration_file"):
        print(f"Created migration: {result['migration_file']}")

        if result.get("changes"):
            print("Changes:")

            for change in result["changes"]:
                print(f"  {change}")
    elif result.get("message"):
        print(result["message"])
    elif result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)

        return 1

    return 0


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

    p_gen = sub.add_parser("generate", help="Generate code from service.yaml")
    p_gen.add_argument("--watch", action="store_true", help="Watch service.yaml for changes and regenerate")
    p_gen.set_defaults(func=cmd_generate)

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
