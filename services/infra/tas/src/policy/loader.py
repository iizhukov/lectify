import yaml
import os

from pathlib import Path
from typing import Generator

from src.policy.models import PermissionRule, PermissionEffect


def _find_service_root() -> Path:
    start = Path.cwd()
    for parent in [start] + list(start.parents):
        candidate = parent / "service.yaml"

        if candidate.exists():
            return parent

    raise RuntimeError("Cannot find service.yaml — are you in a service directory?")


def _find_repo_root(service_root: Path) -> Path:
    env_root = os.environ.get("LECTIFY_ROOT")
    if env_root:
        return Path(env_root)

    for parent in [service_root] + list(service_root.parents):
        if (parent / "services").is_dir() and (parent / "proto").is_dir():
            return parent
        if (parent / ".git").is_dir():
            return parent

    for parent in [service_root] + list(service_root.parents):
        if (parent / "services").is_dir():
            return parent

    raise RuntimeError("Cannot find repo root")


def _iter_service_yamls(repo_root: Path) -> Generator[Path, None, None]:
    services_dir = repo_root / "services"

    if not services_dir.is_dir():
        return

    yield from services_dir.rglob("service.yaml")


def _parse_service_yaml(path: Path) -> tuple[str, list[str]] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            return None
        
        svc = data.get("service", {})
        if not isinstance(svc, dict):
            return None
        
        source_name = svc.get("name", "")
        if not source_name:
            return None
        
        grpc_client = svc.get("grpc_client", {})
        if not isinstance(grpc_client, dict):
            return None
        
        targets = grpc_client.get("services", [])
        if not isinstance(targets, list):
            return None
        
        return source_name, targets
    except ImportError:
        pass

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    source_name = None
    targets: list[str] = []
    in_grpc_client = False
    grpc_client_indent = 0
    in_services = False

    for line in text.splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        if source_name is None and stripped.startswith("name:"):
            source_name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            continue

        if stripped.startswith("grpc_client:"):
            in_grpc_client = True
            grpc_client_indent = indent
            in_services = False
            continue

        if in_grpc_client:
            if indent <= grpc_client_indent and not stripped.startswith("-"):
                in_grpc_client = False
                in_services = False
                continue

            if stripped.startswith("services:"):
                in_services = True
                continue

            if in_services and stripped.startswith("- "):
                target = stripped[2:].strip().strip('"').strip("'")
                if target:
                    targets.append(target)
                continue

    if source_name:
        return source_name, targets

    return None


def load_default_rules(repo_root: Path | None = None) -> list[PermissionRule]:
    if repo_root is None:
        service_root = _find_service_root()
        repo_root = _find_repo_root(service_root)

    rules: list[PermissionRule] = []
    seen: set[tuple[str, str]] = set()

    for manifest_path in _iter_service_yamls(repo_root):
        if "infra/tas" in str(manifest_path):
            continue

        result = _parse_service_yaml(manifest_path)
        if result is None:
            continue

        source_name, targets = result
        for target in targets:
            key = (source_name, target)
            if key in seen:
                continue
            seen.add(key)
            rules.append(PermissionRule(
                source_service=source_name,
                target_service=target,
                effect=PermissionEffect.ALLOW,
                description=f"Default: {source_name} -> {target} (from service.yaml)",
                is_default=True,
            ))

    return rules
