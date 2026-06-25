"""
Container Runner для оркестратора.
Оборачивает PollingContainerRunner и добавляет:
- Сохранение артефактов в MinIO
- Сохранение логов в MinIO
- Обновление метрик ноды в БД
"""
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.docker.runner import PollingContainerRunner, ContainerMetrics
from src.db.repository import ExecutionRepository, ExecutionNodeRepository
from src.utils.storage import MinIOStorage, get_storage
from src.orchestrator.logs import NodeLogManager
from src.utils.logging import get_logger
from src.utils.metrics import get_metrics

logger = get_logger(__name__)


class ContainerRunnerOrchestrator:
    """
    Оборачивает PollingContainerRunner и добавляет персистентность:
    - после выполнения ноды — копирует output.json в MinIO как артефакт
    - после выполнения ноды — копирует node.log в MinIO как лог
    - при изменении метрик — обновляет запись в БД
    """

    def __init__(
        self,
        docker_runner: PollingContainerRunner | None = None,
        execution_repo: ExecutionRepository | None = None,
        execution_node_repo: ExecutionNodeRepository | None = None,
        storage: MinIOStorage | None = None,
    ):
        self.docker_runner = docker_runner or PollingContainerRunner()
        self.exec_repo = execution_repo or ExecutionRepository()
        self.node_repo = execution_node_repo or ExecutionNodeRepository()
        self.storage = storage or get_storage()
        self.log_manager = NodeLogManager(self.storage)
        self._metrics = get_metrics()

    def run(
        self,
        node_exec_id: str,
        plugin_id: str,
        input_data: Dict[str, Any],
        parameters: Dict[str, Any],
        execution_id: str,
        node_id: str,
        timeout_seconds: int = 600,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> Dict[str, Any]:
        """
        Запускает ноду в Docker-контейнере.
        После успешного выполнения копирует output.json в MinIO и сохраняет логи.
        """
        temp_dir = Path(tempfile.gettempdir()) / "lectify" / execution_id / node_id
        temp_dir.mkdir(parents=True, exist_ok=True)

        output_file = temp_dir / "output.json"

        # Логируем в файл, чтобы потом сохранить в MinIO
        log_path = self.log_manager.create_temp_log_file(execution_id, node_id)

        # Собираем последние метрики из polling thread
        latest_metrics: Optional[ContainerMetrics] = None

        def metrics_callback(metrics: ContainerMetrics):
            nonlocal latest_metrics
            latest_metrics = metrics
            self.node_repo.update(
                node_id=node_exec_id,
                cpu_percent=metrics.cpu_percent,
                memory_mb=metrics.memory_mb,
                execution_time_ms=metrics.execution_time_ms,
            )
            self._metrics.node_cpu_percent.labels(node_id=node_id).set(metrics.cpu_percent)
            self._metrics.node_memory_mb.labels(node_id=node_id).set(metrics.memory_mb)

        try:
            output_data = self.docker_runner.run_plugin(
                plugin_id=plugin_id,
                input_data=input_data,
                parameters=parameters,
                execution_id=execution_id,
                node_id=node_id,
                progress_callback=on_progress,
                timeout_seconds=timeout_seconds,
                on_metrics=metrics_callback,
            )

            # Сохраняем output.json из результата контейнера, чтобы он не был удалён
            # при очистке временных файлов в docker_runner
            if output_data and not output_file.exists():
                import json
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(output_data, f)

            # Копируем output.json в MinIO
            if output_file.exists():
                artifact_type = parameters.get("output_type", "data")
                minio_path = self.storage.upload_artifact(
                    str(output_file),
                    workflow_id=execution_id,
                    node_id=node_id,
                    artifact_type=artifact_type,
                )
                logger.info(
                    "node_artifact_saved",
                    execution_id=execution_id,
                    node_id=node_id,
                    minio_path=minio_path
                )

            return output_data

        finally:
            # Сбрасываем gauges после завершения ноды
            self._metrics.node_cpu_percent.labels(node_id=node_id).set(0)
            self._metrics.node_memory_mb.labels(node_id=node_id).set(0)
            # Сохраняем логи в MinIO
            self._upload_node_logs(log_path, execution_id, node_id)

    def _upload_node_logs(
        self,
        log_path: Path,
        execution_id: str,
        node_id: str,
    ) -> Optional[str]:
        """Сохраняет логи ноды в MinIO и удаляет локальную копию."""
        object_name = self.log_manager.save_logs_to_minio(
            log_path, execution_id, node_id, log_type="node"
        )
        if object_name:
            self.log_manager.cleanup_local(log_path)
        return object_name
