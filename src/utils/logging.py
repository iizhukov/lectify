"""
Структурированное логирование с использованием structlog
"""
import sys
import logging
import structlog
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_file: str = "logs/lectify.log"):
    """
    Настройка структурированного логирования
    
    Args:
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Путь к файлу логов
    """
    # Создаём директорию для логов
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Настройка стандартного logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )
    
    # Настройка файлового хендлера
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(getattr(logging, log_level.upper()))
    logging.root.addHandler(file_handler)
    
    # Конфигурация structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
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
