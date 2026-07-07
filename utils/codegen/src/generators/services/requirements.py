import re
from pathlib import Path

from generators.services.base import BaseGenerator


def _base_requirements(svc) -> list[str]:
    deps = [
        "grpcio>=1.60.0",
        "grpcio-tools>=1.60.0",
        "grpcio-reflection>=1.60.0",
        "structlog>=24.0.0",
        "python-dateutil>=2.8.2",
    ]
    if svc.grpc.enabled or svc.grpc_client.enabled:
        deps.append("protobuf>=4.25.0")
        deps.append("mypy-protobuf>=3.5.0")
    # if svc.postgres.enabled:
    #     deps += [
    #         "sqlalchemy[asyncio]>=2.0",
    #         "asyncpg>=0.29.0",
    #         "alembic>=1.13.0",
    #     ]
    # if svc.minio.enabled:
    #     deps.append("minio>=7.2.0")
    # if svc.vault.enabled:
    #     deps.append("hvac>=2.0.0")
    # if svc.kafka_producer.enabled or svc.kafka_consumer.enabled:
    #     deps.append("confluent-kafka>=2.3.0")
    # if svc.config_client.enabled:
    #     deps.append("grpcio>=1.60.0")
    # if svc.observability.enabled:
    #     deps += [
    #         "prometheus-client>=0.19.0",
    #         "prometheus-fastapi-instrumentator>=6.1.0",
    #     ]
    return deps


def _dedup_and_sort(deps: list[str]) -> list[str]:
    seen: dict[str, str] = {}

    for d in deps:
        name = re.split(r"[<>=!~]", d)[0].strip()

        if name not in seen:
            seen[name] = d

    return sorted(seen.values(), key=lambda d: re.split(r"[<>=!~]", d)[0].strip())


def _load_user_requirements(path: Path) -> list[str]:
    if not path.exists():
        return []
    
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()

        if stripped and not stripped.startswith("#"):
            lines.append(stripped)

    return lines


class RequirementsGenerator(BaseGenerator):
    def generate(self) -> None:
        base = _base_requirements(self.svc)
        user_path: Path | None = None

        if self.svc.requirements:
            user_path = self.output.parent / self.svc.requirements
            
        user = _load_user_requirements(user_path) if user_path else []
        merged = _dedup_and_sort(base + user)

        content = "\n".join(merged) + "\n"

        self.write_root("requirements.txt", content)
