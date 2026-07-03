import yaml

from pathlib import Path
from pydantic import ValidationError

from config.models import ServiceManifest
from utils import get_repo_root, get_service_proto


class ServiceManifestError(Exception):
    pass


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
    manifest = load_manifest(path / "service.yaml")
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
