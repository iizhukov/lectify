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


class LoggingFileConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"
    path: str = "logs/app.log"
    max_bytes: int = 10485760
    backup_count: int = 5


class LoggingLokiConfig(BaseModel):
    enabled: bool = False
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    batch_size: int = 100
    flush_interval: int = 5
    max_retries: int = 3
    timeout: int = 10


class LoggingConfig(BaseModel):
    file: LoggingFileConfig = LoggingFileConfig()
    loki: LoggingLokiConfig = LoggingLokiConfig()


class GrpcServerConfig(BaseModel):
    enabled: bool = False
    port: int = 8080


class GrpcClientConfig(BaseModel):
    enabled: bool = False
    services: list[str] = Field(default_factory=list)


class MainConfig(BaseModel):
    enabled: bool = False


class KafkaTopic(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9._-]+$")
    partitions: int = Field(default=3, ge=1)
    replication_factor: int = Field(default=1, ge=1)
    retention_hours: int = Field(default=168, ge=1)


class KafkaProducerConfig(BaseModel):
    enabled: bool = False
    topics: list[str] = Field(default_factory=list)


class KafkaConsumerConfig(BaseModel):
    enabled: bool = False
    topics: list[str] = Field(default_factory=list)
    group_id: str | None = None
    auto_offset_reset: Literal["earliest", "latest"] = "earliest"
    max_poll_records: int = Field(default=100, ge=1)
    max_poll_interval_ms: int = Field(default=300000, ge=1000)


class ObservabilityConfig(BaseModel):
    enabled: bool = True
    log_level: str = 'INFO'
    trace_sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    metrics_enabled: bool = True
    service_name: str | None = None


# class FeatureFlag(BaseModel):
#     key: str = Field(min_length=1)
#     default_value: bool = False
#     description: str = ""


class ConfigConfig(BaseModel):
    enabled: bool = False
    update_interval_seconds: int = Field(default=30, ge=1)


# class ConfigClientConfig(BaseModel):
#     enabled: bool = False
#     flags: list[FeatureFlag] = Field(default_factory=list)


class SchedulerConfig(BaseModel):
    enabled: bool = False
    storage: Literal["memory", "database"] = "memory"


class TicketAuthConfig(BaseModel):
    enabled: bool = False
    tas_service: str = "infra_tas"
    ticket_ttl: int = 60


class HttpConfig(BaseModel):
    enabled: bool = False
    timeout_seconds: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    connect_timeout_seconds: float = Field(default=5, gt=0, le=60, allow_inf_nan=False)
    max_connections: int = Field(default=100, ge=1, le=1000)
    max_keepalive_connections: int = Field(default=20, ge=0, le=1000)


class UserAuthConfig(BaseModel):
    enabled: bool = False
    auth_service: str = Field(default="api_auth", pattern=r"^[a-z][a-z0-9_]*$")
    timeout_seconds: float = Field(default=5.0, gt=0, le=30, allow_inf_nan=False)


class TestingConfig(BaseModel):
    generated_fixtures: bool = True


class WorkflowValidationConfig(BaseModel):
    enabled: bool = False


class PluginAgentConfig(BaseModel):
    enabled: bool = False


class Service(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    python: PythonVersion = Field(default_factory=lambda: PythonVersion(major=3, minor=12))
    description: str = ""
    active: bool = False

    testing: TestingConfig = Field(default_factory=TestingConfig)
    main: MainConfig = Field(default_factory=MainConfig)
    grpc: GrpcServerConfig = Field(default_factory=GrpcServerConfig)
    grpc_client: GrpcClientConfig = Field(default_factory=GrpcClientConfig)
    kafka_producer: KafkaProducerConfig = Field(default_factory=KafkaProducerConfig)
    kafka_consumer: KafkaConsumerConfig = Field(default_factory=KafkaConsumerConfig)

    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    minio: MinioConfig = Field(default_factory=MinioConfig)
    vault: VaultConfig = Field(default_factory=VaultConfig)
    ticket_auth: TicketAuthConfig = Field(default_factory=TicketAuthConfig)
    user_auth: UserAuthConfig = Field(default_factory=UserAuthConfig)
    plugin_agent: PluginAgentConfig = Field(default_factory=PluginAgentConfig)
    plugin_runtime_client: PluginAgentConfig = Field(default_factory=PluginAgentConfig)
    workflow_validation: WorkflowValidationConfig = Field(default_factory=WorkflowValidationConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    config: ConfigConfig = Field(default_factory=ConfigConfig)

    # config_client: ConfigClientConfig = Field(default_factory=ConfigClientConfig)


class ServiceManifest(BaseModel):
    """Root model for service.yaml"""
    model_config = {"extra": "forbid"}
    service: Service
    extensions: dict[str, dict] = Field(default_factory=dict)
