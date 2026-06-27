"""
Структурированное логирование с использованием structlog
"""
import sys
import logging
import json
import structlog
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone


def get_access_log_config():
    """Build uvicorn log config with JSON-formatted access logs to file."""
    try:
        from src.config import config
        log_file = config.log_file
        max_bytes = config.log_file_max_bytes
        backup_count = config.log_file_backup_count
    except Exception:
        log_file = "logs/lectify.log"
        max_bytes = 10 * 1024 * 1024
        backup_count = 5

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "src.utils.logging.AccessLogFormatter",
            },
            "default": {
                "()": "logging.Formatter",
                "fmt": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "INFO",
                "formatter": "json",
                "filename": log_file,
                "maxBytes": max_bytes,
                "backupCount": backup_count,
            },
        },
        "loggers": {
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,
            },
            "uvicorn": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["console"],
        },
    }


ACCESS_LOG_CONFIG = get_access_log_config()


class AccessLogFormatter(logging.Formatter):
    """Formatter that outputs access log lines as structured JSON.

    uvicorn.access emits a single string via LogRecord.getMessage().
    We parse that string to extract: method, path, status, duration, client IP.
    """

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        # uvicorn access log format:
        # '{client} - "{method} {path} HTTP/{proto}" {status} {size} "{ua}" {duration}'
        # Example: '127.0.0.1:12345 - "GET /api/workflows HTTP/1.1" 200 1234 "-" 0.001'
        parts = {}
        try:
            # Extract client IP:port
            client = msg.split(" - ")[0] if " - " in msg else ""
            parts["client_ip"] = client

            # Extract request line: "GET /api/workflows HTTP/1.1"
            after_client = msg.split('"', 1)[1] if '"' in msg else ""
            req_parts = after_client.split('"')[0].split(" ")
            if len(req_parts) >= 3:
                parts["method"] = req_parts[0]
                parts["path"] = req_parts[1]
                parts["http_version"] = req_parts[2]

            # Extract status code (first integer after closing quote)
            import re
            status_match = re.search(r'" (\d{3}) ', msg)
            if status_match:
                parts["status"] = int(status_match.group(1))

            # Extract duration
            duration_match = re.search(r'" ([\d.]+)$', msg)
            if duration_match:
                parts["duration_s"] = float(duration_match.group(1))

            parts["message"] = msg
        except Exception:
            parts["message"] = msg

        parts["timestamp"] = datetime.now(timezone.utc).isoformat()
        parts["logger"] = "uvicorn.access"

        return json.dumps(parts)


def setup_logging(log_level: str = "INFO", log_file: str = "logs/lectify.log"):
    """
    Настройка структурированного логирования с выводом в консоль, файл и MinIO
    
    Args:
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Путь к файлу логов
    """
    try:
        from src.config import config
        log_level = config.log_level
        log_file = config.log_file
    except Exception as e:
        print(f"WARNING: Using default logging config: {str(e)}")
    
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    from logging.handlers import RotatingFileHandler
    
    log_level_obj = getattr(logging, log_level.upper())
    
    logging.root.handlers.clear()
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level_obj)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    logging.root.addHandler(console_handler)
    
    try:
        from src.config import config
        max_bytes = config.log_file_max_bytes
        backup_count = config.log_file_backup_count
    except Exception:
        max_bytes = 10 * 1024 * 1024  # 10MB
        backup_count = 5
    
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    file_handler.setLevel(log_level_obj)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    logging.root.addHandler(file_handler)
    
    # Устанавливаем уровень корневого логгера
    logging.root.setLevel(log_level_obj)
    
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.set_exc_info,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_obj),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Получить логгер с заданным именем
    
    Args:
        name: Имя логгера (обычно __name__)
    
    Returns:
        Настроенный structlog логгер
    """
    return structlog.get_logger(name)


def upload_logs_to_minio(log_file: str = None) -> Optional[str]:
    """
    Загрузить логи в MinIO
    
    Args:
        log_file: Путь к файлу логов (если не указан, используется из конфига)
    
    Returns:
        Путь к объекту в MinIO или None при ошибке
    """
    try:
        from src.utils.storage import MinIOStorage
        from src.config import config
        
        if log_file is None:
            log_file = config.log_file
        
        storage = MinIOStorage()
        storage.ensure_buckets()
        
        logger = get_logger(__name__)
        
        result = storage.upload_log(log_file, log_type="application")
        
        if result:
            logger.info("logs_uploaded_to_minio", object_name=result)
        else:
            logger.warning("logs_upload_to_minio_failed")
        
        return result
        
    except Exception as e:
        print(f"ERROR:  Error uploading logs to MinIO: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return None
