from typing import Literal
from pydantic import BaseModel, Field


class PythonVersion(BaseModel):
    major: int = 3
    minor: int = Field(default=12, ge=10, le=13)


class PostgresConfig(BaseModel):
    enabled: bool = False
    pool_size: int = Field(default=10, ge=1, le=100)
    pool_max_overflow: int = Field(default=5, ge=0, le=50)
    pool_mode: Literal["session", "transaction", "cursor"] = "transaction"
    migration_dir: str | None = "migrations"


class MinioConfig(BaseModel):
    enabled: bool = False
    buckets: list[str] = Field(default_factory=list)


class VaultConfig(BaseModel):
    enabled: bool = True
    vars: list[str] = Field(default_factory=list)


class GrpcServerConfig(BaseModel):
    enabled: bool = False
    port: int = 8080


class GrpcClientConfig(BaseModel):
    enabled: bool = False
    services: list[str] = Field(default_factory=list)


class MainConfig(BaseModel):
    enabled: bool = False


# class KafkaTopic(BaseModel):
#     name: str = Field(pattern=r"^[a-zA-Z0-9._-]+$")
#     partitions: int = Field(default=3, ge=1)
#     replication_factor: int = Field(default=1, ge=1)
#     retention_hours: int = Field(default=168, ge=1)


# class KafkaProducerConfig(BaseModel):
#     enabled: bool = False
#     topics: list[str] = Field(default_factory=list)


# class KafkaConsumerConfig(BaseModel):
#     enabled: bool = False
#     topics: list[str] = Field(default_factory=list)
#     group_id: str | None = None
#     auto_offset_reset: Literal["earliest", "latest"] = "earliest"
#     max_poll_records: int = Field(default=100, ge=1)
#     max_poll_interval_ms: int = Field(default=300000, ge=1000)


# class AuthConfig(BaseModel):
#     enabled: bool = True
#     require_ticket: bool = True
#     allowed_services: list[str] = Field(default_factory=list)


# class FeatureFlag(BaseModel):
#     key: str = Field(min_length=1)
#     default_value: bool = False
#     description: str = ""


# class ConfigClientConfig(BaseModel):
#     enabled: bool = False
#     flags: list[FeatureFlag] = Field(default_factory=list)


# class ObservabilityConfig(BaseModel):
#     enabled: bool = True
#     log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
#     trace_sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
#     metrics_enabled: bool = True
#     service_name: str | None = None
#     metrics_path: str = "/metrics"
#     metrics_port: int = 9090


class Service(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    python: PythonVersion = Field(default_factory=lambda: PythonVersion(major=3, minor=12))
    description: str = ""
    requirements: str | None = None  # path to user requirements file (relative to service root)

    main: MainConfig = Field(default_factory=MainConfig)
    grpc: GrpcServerConfig = Field(default_factory=GrpcServerConfig)
    grpc_client: GrpcClientConfig = Field(default_factory=GrpcClientConfig)
    # kafka_producer: KafkaProducerConfig = Field(default_factory=KafkaProducerConfig)
    # kafka_consumer: KafkaConsumerConfig = Field(default_factory=KafkaConsumerConfig)

    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    minio: MinioConfig = Field(default_factory=MinioConfig)
    vault: VaultConfig = Field(default_factory=VaultConfig)

    # auth: AuthConfig = Field(default_factory=AuthConfig)
    # config_client: ConfigClientConfig = Field(default_factory=ConfigClientConfig)

    # observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)


class ServiceManifest(BaseModel):
    """Root model for service.yaml"""
    service: Service
    extensions: dict[str, dict] = Field(default_factory=dict)
