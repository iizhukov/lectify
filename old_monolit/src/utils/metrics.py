from prometheus_client import Counter, Gauge, Histogram, Summary


class LectifyMetrics:
    def __init__(self):
        # HTTP-метрики
        self.http_requests_total = Counter(
            'lectify_http_requests_total',
            'HTTP requests total',
            ['method', 'path', 'status']
        )

        self.http_request_duration = Histogram(
            'lectify_http_request_duration_seconds',
            'HTTP request duration',
            ['method', 'path'],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
        )

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

        # CPU/memory текущие значения для нод
        self.node_cpu_percent = Gauge(
            'lectify_node_cpu_percent',
            'CPU usage per node',
            ['node_id']
        )

        self.node_memory_mb = Gauge(
            'lectify_node_memory_mb',
            'Memory usage per node in MB',
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

        # Метрики базы данных
        self.db_operations = Counter(
            'lectify_db_operations_total',
            'Количество операций с БД',
            ['operation']
        )

        self.db_operation_duration = Histogram(
            'lectify_db_operation_duration_seconds',
            'Длительность операций с БД',
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5)
        )


_metrics_instance = None


def get_metrics() -> LectifyMetrics:
    global _metrics_instance

    if _metrics_instance is None:
        _metrics_instance = LectifyMetrics()

    return _metrics_instance


# Для обратной совместимости
metrics = get_metrics()
