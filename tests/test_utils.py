"""
Интеграционные тесты для утилит (логирование, метрики)
"""
import pytest
import structlog
from pathlib import Path

from src.utils.logging import setup_logging, get_logger
from src.utils.metrics import get_metrics


@pytest.mark.integration
class TestLogging:
    """Тесты системы логирования"""
    
    def test_setup_logging(self, setup_logging):
        """Тест настройки логирования"""
        log_file = setup_logging
        
        # Проверяем, что директория создана
        assert log_file.parent.exists()
    
    def test_get_logger(self, setup_logging):
        """Тест получения логгера"""
        logger = get_logger("test_module")
        
        assert logger is not None
        # structlog возвращает логгер, проверяем что он есть
        assert hasattr(logger, 'info')
    
    def test_logger_output(self, setup_logging):
        """Тест вывода логов"""
        logger = get_logger("test")
        
        # Просто проверяем что логирование не падает
        try:
            logger.info("test_event", key="value", number=42)
            assert True
        except Exception as e:
            assert False, f"Logging failed: {e}"
    
    def test_logger_levels(self, setup_logging):
        """Тест уровней логирования"""
        logger = get_logger("test")
        
        # Проверяем что разные уровни работают
        try:
            logger.debug("debug_message")
            logger.info("info_message")
            logger.warning("warning_message")
            logger.error("error_message")
            assert True
        except Exception as e:
            assert False, f"Logging failed: {e}"
    
    def test_structured_logging_format(self, setup_logging):
        """Тест структурированного формата логов"""
        logger = get_logger("test")
        
        # Проверяем что структурированное логирование работает
        try:
            logger.info(
                "workflow_started",
                workflow_id="test-123",
                file_id="file-456",
                active_count=2
            )
            assert True
        except Exception as e:
            assert False, f"Structured logging failed: {e}"


@pytest.mark.integration
class TestMetrics:
    """Тесты системы метрик"""

    def test_metrics_initialization(self):
        """Тест инициализации метрик"""
        metrics = get_metrics()

        assert hasattr(metrics, 'workflows_total')
        assert hasattr(metrics, 'workflows_completed')
        assert hasattr(metrics, 'workflows_failed')
        assert hasattr(metrics, 'workflow_queue_size')
        assert hasattr(metrics, 'workflow_active_count')
    
    def test_get_metrics_singleton(self):
        """Тест получения глобального экземпляра метрик"""
        metrics1 = get_metrics()
        metrics2 = get_metrics()
        
        assert metrics1 is metrics2
    
    def test_counter_metrics(self):
        """Тест счётчиков"""
        metrics = get_metrics()
        
        # Увеличиваем счётчик
        initial_value = metrics.workflows_total._value.get()
        metrics.workflows_total.inc()
        new_value = metrics.workflows_total._value.get()
        
        assert new_value == initial_value + 1
    
    def test_gauge_metrics(self):
        """Тест gauge метрик"""
        metrics = get_metrics()
        
        # Устанавливаем значение
        metrics.workflow_queue_size.set(5)
        value = metrics.workflow_queue_size._value.get()
        
        assert value == 5
    
    def test_histogram_metrics(self):
        """Тест histogram метрик"""
        metrics = get_metrics()
        
        # Наблюдаем значения
        metrics.workflow_duration.observe(120.5)
        metrics.workflow_duration.observe(300.0)
        
        # Проверяем, что метрика работает
        assert metrics.workflow_duration._sum.get() > 0
    
    def test_labeled_metrics(self):
        """Тест метрик с лейблами"""
        metrics = get_metrics()
        
        # Увеличиваем с разными лейблами
        metrics.node_failures.labels(node_id="test_node_1").inc()
        metrics.node_failures.labels(node_id="test_node_2").inc()
        metrics.node_failures.labels(node_id="test_node_2").inc()
        
        # Проверяем, что лейблы работают
        assert metrics.node_failures.labels(node_id="test_node_1")._value.get() == 1
        assert metrics.node_failures.labels(node_id="test_node_2")._value.get() == 2
    
    def test_llm_api_metrics(self):
        """Тест метрик LLM API"""
        metrics = get_metrics()
        
        # Запросы
        metrics.llm_api_requests.labels(purpose="smart", status="success").inc()
        metrics.llm_api_requests.labels(purpose="smart", status="error").inc()
        
        # Длительность
        metrics.llm_api_duration.labels(purpose="smart").observe(2.5)
        
        # Ошибки
        metrics.llm_api_errors.labels(purpose="smart", error_type="timeout").inc()
        
        # Проверяем
        assert metrics.llm_api_requests.labels(purpose="smart", status="success")._value.get() >= 1
    
    def test_database_metrics(self):
        """Тест метрик базы данных"""
        metrics = get_metrics()
        
        # Операции
        metrics.db_operations.labels(operation="select", table="files").inc()
        metrics.db_operations.labels(operation="insert", table="workflows").inc()
        
        # Длительность
        metrics.db_operation_duration.labels(operation="select").observe(0.05)
        
        # Проверяем
        assert metrics.db_operations.labels(operation="select", table="files")._value.get() >= 1
    
    def test_error_metrics(self):
        """Тест метрик ошибок"""
        metrics = get_metrics()
        
        metrics.errors_total.labels(component="orchestrator", error_type="timeout").inc()
        metrics.errors_total.labels(component="storage", error_type="connection").inc()
        
        assert metrics.errors_total.labels(component="orchestrator", error_type="timeout")._value.get() >= 1
    
    def test_file_metrics(self):
        """Тест метрик файлов"""
        metrics = get_metrics()
        
        # Загруженные файлы
        metrics.files_uploaded.inc()
        metrics.files_uploaded.inc()
        
        # Размер файлов
        metrics.file_size_bytes.observe(1024 * 1024)  # 1 MB
        metrics.file_size_bytes.observe(512 * 1024)   # 512 KB
        
        assert metrics.files_uploaded._value.get() >= 2
        assert metrics.file_size_bytes._sum.get() > 0
