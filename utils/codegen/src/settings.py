from typing import Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings
from dotenv import dotenv_values

from utils import get_repo_root


class PostgresSettings(BaseModel):
    """PostgreSQL settings"""
    user: str
    password: str
    host: str
    port: int
    
    @property
    def dsn(self) -> str:
        """PostgreSQL DSN"""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{{database}}"


class MinIOSettings(BaseModel):
    """MinIO settings"""
    root_user: str
    root_password: str
    api_port: int
    console_port: int
    
    @property
    def endpoint(self) -> str:
        return f"minio:{self.api_port}"
    
    @property
    def console_url(self) -> str:
        return f"http://localhost:{self.console_port}"


class VaultSettings(BaseModel):
    """Vault settings"""
    token: str
    port: int
    
    @property
    def address(self) -> str:
        return f"http://vault:{self.port}"


class KafkaSettings(BaseModel):
    """Kafka settings"""
    broker_id: int
    port: int
    internal_port: int
    
    @property
    def bootstrap_servers(self) -> str:
        """Internal bootstrap servers for Docker"""
        return f"kafka:{self.internal_port}"
    
    @property
    def bootstrap_servers_host(self) -> str:
        """External bootstrap servers for host"""
        return f"localhost:{self.port}"


class ZookeeperSettings(BaseModel):
    """Zookeeper settings"""
    client_port: int
    tick_time: int
    
    @property
    def connect_string(self) -> str:
        return f"zookeeper:{self.client_port}"


class KafkaUISettings(BaseModel):
    """Kafka UI settings"""
    port: int
    
    @property
    def url(self) -> str:
        return f"http://kafka-ui:{self.port}"


class PrometheusSettings(BaseModel):
    """Prometheus settings"""
    port: int
    
    @property
    def url(self) -> str:
        return f"http://prometheus:{self.port}"


class LokiSettings(BaseModel):
    """Loki settings"""
    port: int
    
    @property
    def url(self) -> str:
        return f"http://loki:{self.port}"


class TempoSettings(BaseModel):
    """Tempo settings"""
    grpc_port: int
    http_port: int
    
    @property
    def grpc_endpoint(self) -> str:
        return f"tempo:{self.grpc_port}"
    
    @property
    def http_endpoint(self) -> str:
        return f"http://tempo:{self.http_port}"


class GrafanaSettings(BaseModel):
    """Grafana settings"""
    port: int
    admin_user: str
    admin_password: str
    
    @property
    def url(self) -> str:
        return f"http://grafana:{self.port}"


class AlertmanagerSettings(BaseModel):
    """Alertmanager settings"""
    port: int
    
    @property
    def url(self) -> str:
        return f"http://alertmanager:{self.port}"


class NginxSettings(BaseModel):
    """Nginx gateway settings"""
    port: int
    
    @property
    def url(self) -> str:
        return f"http://gateway-nginx:{self.port}"


class MkDocsSettings(BaseModel):
    """MkDocs settings"""
    port: int
    
    @property
    def url(self) -> str:
        return f"http://mkdocs:{self.port}"


class NetworkSettings(BaseModel):
    """Network settings"""
    name: str


class Settings(BaseSettings):    
    model_config = {"extra": "forbid"}  # Запрещаем лишние поля
    
    # Postgres
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    
    # MinIO
    MINIO_ROOT_USER: str
    MINIO_ROOT_PASSWORD: str
    MINIO_API_PORT: int
    MINIO_CONSOLE_PORT: int
    
    # Vault
    VAULT_DEV_ROOT_TOKEN_ID: str
    VAULT_PORT: int
    
    # Zookeeper
    ZOOKEEPER_CLIENT_PORT: int
    ZOOKEEPER_TICK_TIME: int
    
    # Kafka
    KAFKA_BROKER_ID: int
    KAFKA_PORT: int
    KAFKA_INTERNAL_PORT: int
    
    # Kafka UI
    KAFKA_UI_PORT: int
    
    # Prometheus
    PROMETHEUS_PORT: int
    
    # Loki
    LOKI_PORT: int
    
    # Tempo
    TEMPO_GRPC_PORT: int
    TEMPO_HTTP_PORT: int
    
    # Grafana
    GRAFANA_PORT: int
    GRAFANA_ADMIN_USER: str
    GRAFANA_ADMIN_PASSWORD: str
    
    # Alertmanager
    ALERTMANAGER_PORT: int
    
    # Nginx
    NGINX_PORT: int
    
    # MkDocs
    MKDOCS_PORT: int
    
    @property
    def postgres(self) -> PostgresSettings:
        return PostgresSettings(
            user=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
        )
    
    @property
    def minio(self) -> MinIOSettings:
        return MinIOSettings(
            root_user=self.MINIO_ROOT_USER,
            root_password=self.MINIO_ROOT_PASSWORD,
            api_port=self.MINIO_API_PORT,
            console_port=self.MINIO_CONSOLE_PORT,
        )
    
    @property
    def vault(self) -> VaultSettings:
        return VaultSettings(
            token=self.VAULT_DEV_ROOT_TOKEN_ID,
            port=self.VAULT_PORT,
        )
    
    @property
    def kafka(self) -> KafkaSettings:
        return KafkaSettings(
            broker_id=self.KAFKA_BROKER_ID,
            port=self.KAFKA_PORT,
            internal_port=self.KAFKA_INTERNAL_PORT,
        )
    
    @property
    def zookeeper(self) -> ZookeeperSettings:
        return ZookeeperSettings(
            client_port=self.ZOOKEEPER_CLIENT_PORT,
            tick_time=self.ZOOKEEPER_TICK_TIME,
        )
    
    @property
    def kafka_ui(self) -> KafkaUISettings:
        return KafkaUISettings(port=self.KAFKA_UI_PORT)
    
    @property
    def prometheus(self) -> PrometheusSettings:
        return PrometheusSettings(port=self.PROMETHEUS_PORT)
    
    @property
    def loki(self) -> LokiSettings:
        return LokiSettings(port=self.LOKI_PORT)
    
    @property
    def tempo(self) -> TempoSettings:
        return TempoSettings(
            grpc_port=self.TEMPO_GRPC_PORT,
            http_port=self.TEMPO_HTTP_PORT,
        )
    
    @property
    def grafana(self) -> GrafanaSettings:
        return GrafanaSettings(
            port=self.GRAFANA_PORT,
            admin_user=self.GRAFANA_ADMIN_USER,
            admin_password=self.GRAFANA_ADMIN_PASSWORD,
        )
    
    @property
    def alertmanager(self) -> AlertmanagerSettings:
        return AlertmanagerSettings(port=self.ALERTMANAGER_PORT)
    
    @property
    def nginx(self) -> NginxSettings:
        return NginxSettings(port=self.NGINX_PORT)
    
    @property
    def mkdocs(self) -> MkDocsSettings:
        return MkDocsSettings(port=self.MKDOCS_PORT)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings

    if _settings is None:
        repo_root = get_repo_root()
        
        env_path = repo_root / ".env"
        if not env_path.exists():
            raise FileNotFoundError(
                f".env file not found at {env_path}"
            )
        
        env_vars = dotenv_values(env_path)
        if not env_vars:
            raise ValueError(
                f".env file at {env_path} is empty or could not be parsed"
            )
        
        _settings = Settings(**env_vars)
    
    return _settings
