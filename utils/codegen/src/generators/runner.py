import shutil

from pathlib import Path
from typing import List

from config.models import ServiceManifest
from utils import get_repo_root, get_service_path

from generators.services.base import BaseGenerator as ServiceBaseGenerator
from generators.services.settings import SettingsGenerator
from generators.services.logger import LoggerGenerator
from generators.services.vault import VaultGenerator
from generators.services.observability import ObservabilityGenerator
from generators.services.db import DbGenerator
from generators.services.s3 import S3Generator
# from generators.auth import AuthGenerator
from generators.services.grpc_server import GrpcServerGenerator
from generators.services.grpc_client import GrpcClientGenerator
from generators.services.kafka_consumer import KafkaConsumerGenerator
from generators.services.kafka_producer import KafkaProducerGenerator
# from generators.config_client import ConfigClientGenerator
# from generators.prometheus_scrape import PrometheusScrapeGenerator
from generators.services.requirements import RequirementsGenerator
from generators.services.main import MainGenerator
from generators.services.dockerfile import DockerfileGenerator

from generators.infra.base import BaseGenerator as InfraBaseGenerator
from generators.infra.minio import MinioGenerator
from generators.infra.postgres import PostgresGenerator
from generators.infra.kafka import KafkaGenerator


def run_service(manifest: ServiceManifest, output_path: Path) -> None:
    if output_path.exists():
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True)

    gens: List[ServiceBaseGenerator] = [
        SettingsGenerator(manifest, output_path),
        LoggerGenerator(manifest, output_path),
        VaultGenerator(manifest, output_path),
        ObservabilityGenerator(manifest, output_path),
        DbGenerator(manifest, output_path),
        S3Generator(manifest, output_path),
        # AuthGenerator(manifest, output_path),
        GrpcServerGenerator(manifest, output_path),
        GrpcClientGenerator(manifest, output_path),
        KafkaConsumerGenerator(manifest, output_path),
        KafkaProducerGenerator(manifest, output_path),
        # ConfigClientGenerator(manifest, output_path),
        RequirementsGenerator(manifest, output_path),
        MainGenerator(manifest, output_path),
        DockerfileGenerator(manifest, output_path),
    ]

    for gen in gens:
        gen.generate()

    print(f"[codegen] Generated {sum(g.files_written for g in gens)} files in {output_path}")


def run_infra(services: list[ServiceManifest]) -> None:
    output_path = get_repo_root() / "infra"

    gens: List[InfraBaseGenerator] = [
        MinioGenerator(services, output_path),
        PostgresGenerator(services, output_path),
        KafkaGenerator(services, output_path),
    ]

    for gen in gens:
        gen.generate()

    print(f"[codegen] Generated {sum(g.files_written for g in gens)} files in {output_path}")


def run_plugins() -> None:
    ...


def run_project(services: list[ServiceManifest]) -> None:
    services = list(filter(lambda s: s.service.active, services))

    for service in services:
        run_service(service, get_service_path(service.service.name) / "generated/")

    run_infra(services)
    run_plugins()
