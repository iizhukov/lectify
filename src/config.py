"""
Конфигурация приложения, читается из config.cfg
"""
import sys
from configparser import ConfigParser
from pathlib import Path


ROOT_DIR = Path(__file__).parent.parent


class Config:
    """Класс для управления конфигурацией приложения"""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """Загрузка конфигурации из config.cfg"""
        config_path = ROOT_DIR / "config.cfg"

        self._config = ConfigParser()

        if not config_path.exists():
            # config.cfg is not required in Docker containers where only
            # plugins run (no DB connection available anyway). Use defaults.
            import warnings
            warnings.warn(f"config.cfg not found at {config_path} — using defaults (Docker mode?)")
            return

        self._config.read(config_path)

        # Валидация критических секций
        self._validate_config()
    
    def _validate_config(self):
        """Валидация критических параметров конфигурации"""
        if not self._config.has_section("OpenAI"):
            raise ValueError("ERROR:  Секция [OpenAI] не найдена в config.cfg")
        
        if not self._config.has_option("OpenAI", "API_KEY"):
            raise ValueError("ERROR:  Параметр API_KEY не найден в секции [OpenAI]")
        
        if not self._config.has_option("OpenAI", "URL"):
            raise ValueError("ERROR:  Параметр URL не найден в секции [OpenAI]")
    
    # ========================================================================
    # OpenAI Configuration
    # ========================================================================
    
    @property
    def openai_api_key(self) -> str:
        """OpenAI API ключ"""
        import os as _os
        return _os.environ.get("OPENAI_API_KEY") or self._config.get("OpenAI", "API_KEY", fallback="")
    
    @property
    def openai_api_url(self) -> str:
        """OpenAI API URL"""
        import os as _os
        return _os.environ.get("OPENAI_API_URL") or self._config.get("OpenAI", "URL", fallback="")
    
    @property
    def openai_model(self) -> str:
        """OpenAI модель по умолчанию"""
        return self._config.get("OpenAI", "MODEL", fallback="deepseek/deepseek-r1")
    
    @property
    def openai_reasoning(self) -> bool:
        """Использовать reasoning"""
        return self._config.getboolean("OpenAI", "REASONING", fallback=False)
    
    @property
    def openai_stream(self) -> bool:
        """Использовать streaming"""
        return self._config.getboolean("OpenAI", "STREAM", fallback=False)
    
    # ========================================================================
    # Database Configuration
    # ========================================================================
    
    def _get_database_connection_url(self, test: bool = False) -> str:
        """Построить PostgreSQL connection URL"""
        section = "Database.Test" if test else "Database"
        
        if self._config.has_option(section, "CONNECTION_URL"):
            return self._config.get(section, "CONNECTION_URL")
        
        driver = self._config.get("Database", "DRIVER", fallback="postgresql")
        username = self._config.get("Database", "USERNAME", fallback="lectify")
        password = self._config.get("Database", "PASSWORD", fallback="lectify_password")
        host = self._config.get("Database", "HOST", fallback="localhost")
        port = self._config.get("Database", "PORT", fallback="5432")
        database = self._config.get(section, "DATABASE", fallback="lectify" if not test else "lectify_test")
        
        return f"{driver}://{username}:{password}@{host}:{port}/{database}"
    
    @property
    def database_url(self) -> str:
        """Production database URL"""
        return self._get_database_connection_url(test=False)
    
    @property
    def database_test_url(self) -> str:
        """Test database URL"""
        return self._get_database_connection_url(test=True)
    
    @property
    def database_pool_size(self) -> int:
        """Connection pool size"""
        return self._config.getint("Database", "POOL_SIZE", fallback=10)
    
    @property
    def database_max_overflow(self) -> int:
        """Maximum overflow connections"""
        return self._config.getint("Database", "MAX_OVERFLOW", fallback=20)
    
    # ========================================================================
    # MinIO Configuration
    # ========================================================================
    
    @property
    def minio_endpoint(self) -> str:
        """MinIO endpoint — env var overrides config file."""
        import os
        return os.environ.get("MINIO_ENDPOINT") or self._config.get("MinIO", "ENDPOINT", fallback="localhost:9000")
    
    @property
    def minio_access_key(self) -> str:
        """MinIO access key"""
        return self._config.get("MinIO", "ACCESS_KEY", fallback="minioadmin")
    
    @property
    def minio_secret_key(self) -> str:
        """MinIO secret key"""
        return self._config.get("MinIO", "SECRET_KEY", fallback="minioadmin")
    
    @property
    def minio_secure(self) -> bool:
        """Использовать HTTPS для MinIO"""
        return self._config.getboolean("MinIO", "SECURE", fallback=False)
    
    @property
    def minio_artifacts_bucket(self) -> str:
        """Бакет для артефактов"""
        return self._config.get("MinIO", "ARTIFACTS_BUCKET", fallback="artifacts")
    
    @property
    def minio_logs_bucket(self) -> str:
        """Бакет для логов"""
        return self._config.get("MinIO", "LOGS_BUCKET", fallback="logs")
    
    # ========================================================================
    # Monitoring Configuration
    # ========================================================================
    
    @property
    def prometheus_enabled(self) -> bool:
        """Включена ли Prometheus метрика"""
        return self._config.getboolean("Monitoring", "PROMETHEUS_ENABLED", fallback=True)
    
    @property
    def prometheus_port(self) -> int:
        """Порт Prometheus"""
        return self._config.getint("Monitoring", "PROMETHEUS_PORT", fallback=8000)
    
    @property
    def grafana_enabled(self) -> bool:
        """Включена ли Grafana"""
        return self._config.getboolean("Monitoring", "GRAFANA_ENABLED", fallback=True)
    
    @property
    def grafana_port(self) -> int:
        """Порт Grafana"""
        return self._config.getint("Monitoring", "GRAFANA_PORT", fallback=3000)
    
    @property
    def grafana_admin_user(self) -> str:
        """Админ пользователь Grafana"""
        return self._config.get("Monitoring", "GRAFANA_ADMIN_USER", fallback="admin")
    
    @property
    def grafana_admin_password(self) -> str:
        """Админ пароль Grafana"""
        return self._config.get("Monitoring", "GRAFANA_ADMIN_PASSWORD", fallback="admin")
    
    @property
    def loki_enabled(self) -> bool:
        """Включена ли Loki"""
        return self._config.getboolean("Monitoring", "LOKI_ENABLED", fallback=True)
    
    @property
    def loki_url(self) -> str:
        """URL Loki"""
        return self._config.get("Monitoring", "LOKI_URL", fallback="http://localhost:3100")
    
    @property
    def loki_tenant_id(self) -> str:
        """Tenant ID для Loki"""
        return self._config.get("Monitoring", "LOKI_TENANT_ID", fallback="lectify")
    
    @property
    def alertmanager_enabled(self) -> bool:
        """Включен ли Alertmanager"""
        return self._config.getboolean("Monitoring", "ALERTMANAGER_ENABLED", fallback=True)
    
    @property
    def alertmanager_url(self) -> str:
        """URL Alertmanager"""
        return self._config.get("Monitoring", "ALERTMANAGER_URL", fallback="http://localhost:9093")

    @property
    def telegram_enabled(self) -> bool:
        """Включен ли Telegram"""
        return self._config.getboolean("Monitoring", "TELEGRAM_ENABLED", fallback=False)

    @property
    def telegram_bot_token(self) -> str:
        """Telegram bot token"""
        return self._config.get("Monitoring", "TELEGRAM_BOT_TOKEN", fallback="")

    @property
    def telegram_chat_id(self) -> str:
        """Telegram chat ID"""
        return self._config.get("Monitoring", "TELEGRAM_CHAT_ID", fallback="")

    # ========================================================================
    # Logging Configuration
    # ========================================================================
    
    @property
    def log_level(self) -> str:
        """Уровень логирования"""
        return self._config.get("Logging", "LOG_LEVEL", fallback="INFO")
    
    @property
    def log_file(self) -> str:
        """Путь к файлу логов"""
        return self._config.get("Logging", "LOG_FILE", fallback="logs/lectify.log")
    
    @property
    def upload_logs_to_minio(self) -> bool:
        """Загружать ли логи в MinIO"""
        return self._config.getboolean("Logging", "UPLOAD_LOGS_TO_MINIO", fallback=True)
    
    @property
    def log_file_max_bytes(self) -> int:
        """Максимальный размер лог-файла в байтах"""
        return self._config.getint("Logging", "LOG_FILE_MAX_BYTES", fallback=10485760)
    
    @property
    def log_file_backup_count(self) -> int:
        """Количество резервных лог-файлов"""
        return self._config.getint("Logging", "LOG_FILE_BACKUP_COUNT", fallback=5)

    # ========================================================================
    # Plugins Configuration
    # ========================================================================

    @property
    def plugins_build_on_startup(self) -> bool:
        """Собирать Docker-образы плагинов при старте приложения"""
        return self._config.getboolean("Plugins", "BUILD_ON_STARTUP", fallback=False)

    @property
    def plugins_registry(self) -> str:
        """Container registry prefix (e.g. ghcr.io/owner/repo or docker.io/user).
        Empty string = no registry push/pull (local images only)."""
        return self._config.get("Plugins", "REGISTRY", fallback="")

    @property
    def plugins_registry_user(self) -> str:
        """Registry username (for docker login). Uses GITHUB_ACTOR env var if empty."""
        return self._config.get("Plugins", "REGISTRY_USER", fallback="")

    @property
    def plugins_registry_password(self) -> str:
        """Registry password/token. Uses GITHUB_TOKEN env var if empty (CI)."""
        return self._config.get("Plugins", "REGISTRY_PASSWORD", fallback="")

    # ========================================================================
    # Orchestrator Configuration
    # ========================================================================

    @property
    def orchestrator_enabled(self) -> bool:
        """Включен ли оркестратор"""
        return self._config.getboolean("Orchestrator", "ENABLED", fallback=True)

    @property
    def orchestrator_max_concurrent_nodes(self) -> int:
        """Максимальное количество одновременно выполняемых нод"""
        return self._config.getint("Orchestrator", "MAX_CONCURRENT_NODES", fallback=5)

    @property
    def orchestrator_max_concurrent_workflows(self) -> int:
        """Максимальное количество одновременных воркфлоу (для обратной совместимости)"""
        return self._config.getint("Orchestrator", "MAX_CONCURRENT_WORKFLOWS", fallback=100)

    @property
    def orchestrator_poll_interval_seconds(self) -> int:
        """Интервал опроса БД (секунды)"""
        return self._config.getint("Orchestrator", "POLL_INTERVAL_SECONDS", fallback=5)

    @property
    def orchestrator_node_timeout_seconds(self) -> int:
        """Таймаут выполнения одной ноды (секунды)"""
        return self._config.getint("Orchestrator", "NODE_TIMEOUT_SECONDS", fallback=600)

    @property
    def orchestrator_auto_retry_failed_nodes(self) -> bool:
        """Автоматически перезапускать упавшие ноды"""
        return self._config.getboolean("Orchestrator", "AUTO_RETRY_FAILED_NODES", fallback=True)

    @property
    def orchestrator_max_node_retries(self) -> int:
        """Максимальное количество перезапусков ноды"""
        return self._config.getint("Orchestrator", "MAX_NODE_RETRIES", fallback=2)


config = Config()
