import shutil

from pathlib import Path
from typing import List

from config.models import ServiceManifest

from generators.base import BaseGenerator
from generators.settings import SettingsGenerator
from generators.vault import VaultGenerator
# from generators.observability import ObservabilityGenerator
from generators.db import DbGenerator
from generators.s3 import S3Generator
# from generators.auth import AuthGenerator
from generators.grpc_server import GrpcServerGenerator
from generators.grpc_client import GrpcClientGenerator
# from generators.kafka_consumer import KafkaConsumerGenerator
# from generators.kafka_producer import KafkaProducerGenerator
# from generators.config_client import ConfigClientGenerator
# from generators.mocks import MocksGenerator
# from generators.libs import LibsGenerator
# from generators.docker_compose import DockerComposeGenerator
# from generators.prometheus_scrape import PrometheusScrapeGenerator
# from generators.minio_init import MinioInitGenerator
from generators.requirements import RequirementsGenerator
from generators.main import MainGenerator
from generators.dockerfile import DockerfileGenerator


def run_all(manifest: ServiceManifest, output_path: Path) -> None:
    if output_path.exists():
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True)

    gens: List[BaseGenerator] = [
        SettingsGenerator(manifest, output_path),
        VaultGenerator(manifest, output_path),
        # ObservabilityGenerator(manifest, output_path),
        DbGenerator(manifest, output_path),
        S3Generator(manifest, output_path),
        # AuthGenerator(manifest, output_path),
        GrpcServerGenerator(manifest, output_path),
        GrpcClientGenerator(manifest, output_path),
        # KafkaConsumerGenerator(manifest, output_path),
        # KafkaProducerGenerator(manifest, output_path),
        # ConfigClientGenerator(manifest, output_path),
        # MocksGenerator(manifest, output_path),
        # LibsGenerator(manifest, output_path),
        # DockerComposeGenerator(manifest, output_path),
        # PrometheusScrapeGenerator(manifest, output_path),
        # MinioInitGenerator(manifest, output_path),
        RequirementsGenerator(manifest, output_path),
        MainGenerator(manifest, output_path),
        DockerfileGenerator(manifest, output_path),
    ]

    for gen in gens:
        gen.generate()

    print(f"[codegen] Generated {sum(g.files_written for g in gens)} files in {output_path}")
