"""
Структурированное логирование с использованием structlog
"""
import sys
import logging
import structlog
from pathlib import Path
from typing import Optional


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
    
    # Создаём директорию для логов
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
