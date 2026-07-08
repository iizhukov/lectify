import yaml

import sys
import os

from pydantic import ValidationError
from pathlib import Path

from config.models import ServiceManifest


class ServiceManifestError(Exception):
    pass


def get_repo_root() -> Path:
    root_env = os.environ.get("LECTIFY_ROOT")

    if not root_env:
        raise ValueError("LECTIFY_ROOT environment variable not set")

    return Path(root_env)


def get_service_proto(service: Path) -> Path:
    if service.parts[-1] == "service.yaml":
        service = service.parent

    relative_path = service.relative_to(get_repo_root())

    if not relative_path.parts or relative_path.parts[0] != "services":
        raise ValueError(f"Service must be in a 'services' directory")

    in_service_path = relative_path.relative_to("services")
    
    return get_repo_root() / "proto" / in_service_path / "index.proto"


def get_service_path(service_name: str) -> Path:
    repo_root = get_repo_root()
    
    for manifest_path in repo_root.rglob("service.yaml"):
        manifest = get_service_manifest(manifest_path)

        if manifest.service.name == service_name:
            return manifest_path.parent
    
    raise ValueError(f"Service \"{service_name}\" not found")


def get_service_manifest(service_path: Path) -> ServiceManifest:
    manifest_path = service_path

    if service_path.parts[-1] != "service.yaml":
        manifest_path /= "service.yaml"

    try:
        return load_manifest(manifest_path)
    except ServiceManifestError as e:
        print(f"[codegen] ERROR: {e}", file=sys.stderr)
        raise


def load_manifest(path: str | Path) -> ServiceManifest:
    path = Path(path)
    if not path.exists():
        raise ServiceManifestError(f"File not found: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ServiceManifestError(f"Invalid YAML: {e}") from e

    if not isinstance(data, dict):
        raise ServiceManifestError("service.yaml must be a dictionary at root")

    try:
        return ServiceManifest.model_validate(data)
    except ValidationError as e:
        lines = [f"  {err['loc']}: {err['msg']}" for err in e.errors()]
        raise ServiceManifestError(f"service.yaml validation failed:\n" + "\n".join(lines)) from e


def validate_manifest(path: Path) -> list[str]:
    if path.parts[-1] != "service.yaml":
        path /= "service.yaml"

    manifest = load_manifest(path)
    warnings: list[str] = []
    svc = manifest.service

    if svc.grpc.enabled:
        proto_path = get_service_proto(path)

        if not proto_path.exists():
            warnings.append(f"gRPC enabled but proto file not found: {proto_path}")

    # if svc.kafka_producer.enabled and not svc.kafka_producer.topics:
    #     warnings.append("Kafka producer enabled but no topics configured")

    # if svc.kafka_consumer.enabled and not svc.kafka_consumer.topics:
    #     warnings.append("Kafka consumer enabled but no topics configured")

    # if svc.config_client.enabled and not svc.config_client.flags:
    #     warnings.append("Config client enabled but no feature flags defined")

    return warnings
