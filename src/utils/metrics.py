"""
Prometheus метрики для мониторинга приложения
"""
from prometheus_client import Counter, Gauge, Histogram, Summary
from typing import Dict


class LectifyMetrics:
    """Класс для управления метриками Prometheus"""
    
    def __init__(self):
        # Счётчики воркфлоу
        self.workflows_total = Counter(
            'lectify_workflows_total',
            'Общее количество запущенных воркфлоу'
        )
        
        self.workflows_completed = Counter(
            'lectify_workflows_completed_total',
            'Количество успешно завершённых воркфлоу'
        )
        
        self.workflows_failed = Counter(
            'lectify_workflows_failed_total',
            'Количество неудачных воркфлоу'
        )
        
        # Метрики очереди
        self.workflow_queue_size = Gauge(
            'lectify_workflow_queue_size',
            'Текущий размер очереди воркфлоу'
        )
        
        self.workflow_active_count = Gauge(
            'lectify_workflow_active_count',
            'Количество активных воркфлоу'
        )
        
        # Длительность воркфлоу
        self.workflow_duration = Histogram(
            'lectify_workflow_duration_seconds',
            'Длительность выполнения воркфлоу',
            buckets=(30, 60, 120, 300, 600, 1200, 1800, 3600, 7200)
        )
        
        # Метрики нод
        self.node_execution_duration = Histogram(
            'lectify_node_execution_seconds',
            'Длительность выполнения ноды',
            ['node_id'],
            buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200)
        )
        
        self.node_failures = Counter(
            'lectify_node_failures_total',
            'Количество ошибок выполнения нод',
            ['node_id']
        )
        
        # Метрики LLM API
        self.llm_api_requests = Counter(
            'lectify_llm_api_requests_total',
            'Количество запросов к LLM API',
            ['purpose', 'status']
        )
        
        self.llm_api_duration = Histogram(
            'lectify_llm_api_duration_seconds',
            'Длительность запросов к LLM API',
            ['purpose'],
            buckets=(1, 5, 10, 30, 60, 120, 300)
        )
        
        self.llm_api_errors = Counter(
            'lectify_llm_api_errors_total',
            'Количество ошибок LLM API',
            ['purpose', 'error_type']
        )
        
        # Метрики файлов
        self.files_uploaded = Counter(
            'lectify_files_uploaded_total',
            'Количество загруженных файлов'
        )
        
        self.file_size_bytes = Summary(
            'lectify_file_size_bytes',
            'Размер загруженных файлов в байтах'
        )
        
        # Общие метрики ошибок
        self.errors_total = Counter(
            'lectify_errors_total',
            'Общее количество ошибок',
            ['component', 'error_type']
        )
        
        # Метрики базы данных
        self.db_operations = Counter(
            'lectify_db_operations_total',
            'Количество операций с БД',
            ['operation', 'table']
        )
        
        self.db_operation_duration = Histogram(
            'lectify_db_operation_duration_seconds',
            'Длительность операций с БД',
            ['operation'],
            buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0)
        )


# Глобальный экземпляр метрик
metrics = LectifyMetrics()


def get_metrics() -> LectifyMetrics:
    """Получить глобальный экземпляр метрик"""
    return metrics
