"""Comprehensive tests for service.yaml schema validation models."""

import pytest
from pydantic import ValidationError

from config.models import (
    ServiceManifest,
    PythonVersion,
    KafkaTopic,
    KafkaConsumerConfig,
    PostgresConfig,
    MinioConfig,
    VaultConfig,
    SchedulerConfig,
    TicketAuthConfig,
    ConfigConfig,
    LoggingFileConfig,
    LoggingLokiConfig,
    ObservabilityConfig,
)


class TestServiceManifest:
    def test_minimal_service(self):
        data = {"service": {"name": "my-service"}}
        manifest = ServiceManifest.model_validate(data)
        assert manifest.service.name == "my-service"
        assert manifest.service.version == "0.1.0"
        assert manifest.service.active is False
        assert manifest.service.postgres.enabled is False
        assert manifest.service.observability.enabled is True
        assert manifest.service.config.enabled is False
        assert manifest.service.ticket_auth.enabled is False
        assert manifest.service.scheduler.enabled is False
        assert manifest.extensions == {}

    def test_full_service(self):
        data = {
            "service": {
                "name": "user-service",
                "version": "1.2.3",
                "description": "User management service",
                "active": True,
                "python": {"major": 3, "minor": 12},
                "main": {"enabled": True},
                "grpc": {"enabled": True, "port": 9000},
                "grpc_client": {"enabled": True, "services": ["auth_service", "billing_service"]},
                "kafka_producer": {"enabled": True, "topics": ["users.created", "users.updated"]},
                "kafka_consumer": {
                    "enabled": True,
                    "topics": ["orders.completed"],
                    "group_id": "user-consumer",
                    "auto_offset_reset": "earliest",
                    "max_poll_records": 50,
                    "max_poll_interval_ms": 60000,
                },
                "postgres": {
                    "enabled": True,
                    "pool_size": 20,
                    "pool_max_overflow": 10,
                    "pool_mode": "transaction",
                    "migration_dir": "custom_migrations",
                },
                "minio": {"enabled": True, "buckets": ["avatars", "documents"]},
                "vault": {"enabled": True, "vars": ["DB_PASSWORD", "SECRET_KEY"]},
                "scheduler": {"enabled": True, "storage": "memory"},
                "ticket_auth": {"enabled": True, "tas_service": "infra_tas", "ticket_ttl": 120},
                "config": {"enabled": True, "update_interval_seconds": 15},
                "logging": {
                    "file": {"level": "DEBUG", "path": "logs/test.log", "max_bytes": 5000000, "backup_count": 3},
                    "loki": {"enabled": True, "level": "INFO", "batch_size": 50, "flush_interval": 2},
                },
                "observability": {
                    "enabled": True,
                    "log_level": "DEBUG",
                    "trace_sampling_rate": 0.5,
                    "metrics_enabled": True,
                    "service_name": "custom_user_svc",
                },
            },
            "extensions": {"custom_ext": {"key": "value"}},
        }
        manifest = ServiceManifest.model_validate(data)
        assert manifest.service.name == "user-service"
        assert manifest.service.version == "1.2.3"
        assert manifest.service.grpc.port == 9000
        assert manifest.service.postgres.pool_size == 20
        assert manifest.service.ticket_auth.ticket_ttl == 120
        assert manifest.service.config.update_interval_seconds == 15
        assert manifest.service.observability.trace_sampling_rate == 0.5
        assert manifest.extensions["custom_ext"]["key"] == "value"


class TestServiceNameValidation:
    @pytest.mark.parametrize("valid_name", [
        "auth",
        "auth_service",
        "auth-service",
        "my_micro_service_1",
        "a",
    ])
    def test_valid_service_names(self, valid_name):
        manifest = ServiceManifest.model_validate({"service": {"name": valid_name}})
        assert manifest.service.name == valid_name

    @pytest.mark.parametrize("invalid_name", [
        "Auth",               # starts with uppercase
        "AuthService",        # camelCase / PascalCase
        "123service",         # starts with digit
        "-service",           # starts with hyphen
        "_service",           # starts with underscore
        "service name",       # contains space
        "service$name",       # contains special character
        "",                   # empty string
    ])
    def test_invalid_service_names(self, invalid_name):
        with pytest.raises(ValidationError):
            ServiceManifest.model_validate({"service": {"name": invalid_name}})


class TestVersionValidation:
    @pytest.mark.parametrize("valid_version", [
        "0.1.0",
        "1.0.0",
        "12.34.56",
    ])
    def test_valid_versions(self, valid_version):
        manifest = ServiceManifest.model_validate({"service": {"name": "test_svc", "version": valid_version}})
        assert manifest.service.version == valid_version

    @pytest.mark.parametrize("invalid_version", [
        "1.0",
        "v1.0.0",
        "1",
        "latest",
        "1.0.0.0",
    ])
    def test_invalid_versions(self, invalid_version):
        with pytest.raises(ValidationError):
            ServiceManifest.model_validate({"service": {"name": "test_svc", "version": invalid_version}})


class TestPythonConfig:
    def test_default_python_version(self):
        cfg = PythonVersion()
        assert cfg.major == 3
        assert cfg.minor == 12

    @pytest.mark.parametrize("minor", [10, 11, 12, 13])
    def test_valid_python_versions(self, minor):
        cfg = PythonVersion(major=3, minor=minor)
        assert cfg.major == 3
        assert cfg.minor == minor

    def test_invalid_minor_version_too_old(self):
        with pytest.raises(ValidationError):
            PythonVersion(major=3, minor=9)

    def test_invalid_minor_version_too_new(self):
        with pytest.raises(ValidationError):
            PythonVersion(major=3, minor=14)


class TestKafkaTopic:
    def test_valid_kafka_topic(self):
        topic = KafkaTopic(name="users.events_v1", partitions=5, replication_factor=2, retention_hours=72)
        assert topic.name == "users.events_v1"
        assert topic.partitions == 5
        assert topic.replication_factor == 2
        assert topic.retention_hours == 72

    def test_invalid_kafka_topic_name(self):
        with pytest.raises(ValidationError):
            KafkaTopic(name="invalid topic name!")

    def test_invalid_kafka_topic_partitions(self):
        with pytest.raises(ValidationError):
            KafkaTopic(name="valid.topic", partitions=0)


class TestComponentConfigs:
    def test_config_section(self):
        cfg = ConfigConfig(enabled=True, update_interval_seconds=45)
        assert cfg.enabled is True
        assert cfg.update_interval_seconds == 45

    def test_config_section_invalid_interval(self):
        with pytest.raises(ValidationError):
            ConfigConfig(enabled=True, update_interval_seconds=0)

    def test_ticket_auth_defaults(self):
        cfg = TicketAuthConfig()
        assert cfg.enabled is False
        assert cfg.tas_service == "infra_tas"
        assert cfg.ticket_ttl == 60

    def test_postgres_pool_mode(self):
        for mode in ["session", "transaction", "cursor"]:
            cfg = PostgresConfig(pool_mode=mode)
            assert cfg.pool_mode == mode

        with pytest.raises(ValidationError):
            PostgresConfig(pool_mode="invalid_mode")

    def test_scheduler_storage(self):
        cfg_mem = SchedulerConfig(storage="memory")
        assert cfg_mem.storage == "memory"

        cfg_db = SchedulerConfig(storage="database")
        assert cfg_db.storage == "database"

        with pytest.raises(ValidationError):
            SchedulerConfig(storage="redis")

    def test_kafka_consumer_auto_offset(self):
        cfg_earliest = KafkaConsumerConfig(auto_offset_reset="earliest")
        assert cfg_earliest.auto_offset_reset == "earliest"

        cfg_latest = KafkaConsumerConfig(auto_offset_reset="latest")
        assert cfg_latest.auto_offset_reset == "latest"

        with pytest.raises(ValidationError):
            KafkaConsumerConfig(auto_offset_reset="none")

    def test_logging_file_levels(self):
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            cfg = LoggingFileConfig(level=level)
            assert cfg.level == level

        with pytest.raises(ValidationError):
            LoggingFileConfig(level="VERBOSE")

    def test_logging_loki_config(self):
        cfg = LoggingLokiConfig(enabled=True, batch_size=200, flush_interval=10, max_retries=5, timeout=15)
        assert cfg.enabled is True
        assert cfg.batch_size == 200
        assert cfg.flush_interval == 10
        assert cfg.max_retries == 5
        assert cfg.timeout == 15

    def test_observability_sampling_rate(self):
        cfg = ObservabilityConfig(trace_sampling_rate=0.75)
        assert cfg.trace_sampling_rate == 0.75

        with pytest.raises(ValidationError):
            ObservabilityConfig(trace_sampling_rate=1.5)

        with pytest.raises(ValidationError):
            ObservabilityConfig(trace_sampling_rate=-0.1)

    def test_minio_and_vault_configs(self):
        minio = MinioConfig(enabled=True, buckets=["bucket1", "bucket2"])
        assert minio.enabled is True
        assert len(minio.buckets) == 2

        vault = VaultConfig(enabled=True, vars=["KEY_A", "KEY_B"])
        assert vault.enabled is True
        assert "KEY_A" in vault.vars