"""
Container Runner для оркестратора.
Оборачивает PollingContainerRunner и добавляет:
- Сохранение артефактов в MinIO
- Создание DBFile для каждого загруженного артефакта (для связи с БД)
- Сохранение логов в MinIO
- Обновление метрик ноды в БД
"""
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.docker.runner import PollingContainerRunner, ContainerMetrics, cleanup_temp_files
from src.db.repository import ExecutionRepository, ExecutionNodeRepository
from src.utils.storage import MinIOStorage, get_storage
from src.orchestrator.logs import NodeLogManager
from src.utils.logging import get_logger
from src.utils.metrics import get_metrics

logger = get_logger(__name__)


def _parameters_for_artifact_type(ext: str) -> str:
    """Map file extension to artifact_type for MinIO upload."""
    mapping = {
        "m4a": "audio", "mp3": "audio", "wav": "audio", "ogg": "audio",
        "mp4": "video", "mkv": "video", "avi": "video", "mov": "video",
        "txt": "text", "md": "text", "tex": "text",
        "pdf": "pdf",
    }
    return mapping.get(ext.lower(), "data")


def _replace_paths_in_dict(data: Any, uploaded: Dict[str, str]) -> Any:
    """
    Recursively replace container paths in data with MinIO object names.
    If a string value contains a filename key from `uploaded`, replace it.
    """
    if isinstance(data, dict):
        return {k: _replace_paths_in_dict(v, uploaded) for k, v in data.items()}
    elif isinstance(data, list):
        return [_replace_paths_in_dict(item, uploaded) for item in data]
    elif isinstance(data, str):
        for filename, minio_path in uploaded.items():
            if filename in data:
                return minio_path
        return data
    return data


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
        attempt: int = 1,
        log_type: str | None = None,
    ) -> Dict[str, Any]:
        """
        Запускает ноду в Docker-контейнере.
        После успешного выполнения копирует output.json в MinIO и сохраняет логи.
        """
        temp_dir = Path(tempfile.gettempdir()) / "lectify" / execution_id / node_id
        temp_dir.mkdir(parents=True, exist_ok=True)

        output_file = temp_dir / "output" / "output.json"

        # Логируем в файл, чтобы потом сохранить в MinIO
        effective_log_type = log_type or plugin_id
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
                log_path=str(log_path),
            )

            # Upload output files (excluding output.json) to MinIO and update output_data
            output_data = self._upload_output_files(
                output_data, temp_dir, execution_id, node_id
            )
            logger.info(
                f"_upload_output_files_result "
                f"execution_id={execution_id} node_id={node_id} "
                f"output_data_keys={list(output_data.keys()) if output_data else None} "
                f"txt_path={output_data.get('txt_path') if output_data else None} "
                f"file_id={output_data.get('file_id') if output_data else None}"
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
            minio_logs_path = self._upload_node_logs(log_path, execution_id, node_id, attempt=attempt, log_type=effective_log_type)
            if minio_logs_path:
                self.node_repo.update(node_id=node_exec_id, logs_path=minio_logs_path)
            # Удаляем временные файлы после загрузки в MinIO
            cleanup_temp_files(execution_id, node_id)

    def _create_db_file(
        self,
        file_path: str,
        minio_path: str,
    ) -> str:
        """
        Create a DBFile record for an uploaded artifact.
        Returns the new file_id.
        """
        import os
        from src.db.database import SessionLocal
        from src.db.entity import DBFile

        new_file_id = str(uuid.uuid4())
        filename = Path(file_path).name
        stat = os.stat(file_path)
        size_bytes = stat.st_size

        mime_type_map = {
            ".m4a": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".mp4": "video/mp4",
            ".mkv": "video/x-matroska",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".tex": "text/x-tex",
            ".pdf": "application/pdf",
        }
        mime_type = mime_type_map.get(Path(file_path).suffix.lower(), "application/octet-stream")

        with SessionLocal() as session:
            db_file = DBFile(
                id=new_file_id,
                filename=filename,
                original_path=minio_path,
                language="",
                status="ready",
                size_bytes=size_bytes,
                mime_type=mime_type,
                minio_path=minio_path,
            )
            session.add(db_file)
            session.commit()

        return new_file_id

    def _upload_output_files(
        self,
        output_data: Dict[str, Any],
        temp_dir: Path,
        execution_id: str,
        node_id: str,
    ) -> Dict[str, Any]:
        """
        Scan /output/ directory for files created by the plugin (excluding output.json),
        upload each to MinIO, create a DBFile record with the minio_path,
        and update output_data with the new file_id and minio:// URL.
        """
        if output_data is None:
            return output_data

        output_dir = temp_dir / "output"
        if not output_dir.exists():
            logger.warning(
                "output_dir_missing",
                execution_id=execution_id,
                node_id=node_id,
                output_dir=str(output_dir),
            )
            return output_data

        all_files = list(output_dir.iterdir())
        logger.info(
            "output_dir_scan",
            execution_id=execution_id,
            node_id=node_id,
            output_dir=str(output_dir),
            files=[f.name for f in all_files],
        )

        uploaded = {}  # filename -> (new_file_id, full_minio_url)
        field_file_ids = {}  # output key -> new_file_id (for file_id proxying)
        for f in output_dir.iterdir():
            if f.name == "output.json":
                continue
            artifact_type = _parameters_for_artifact_type(f.suffix.lstrip("."))
            minio_path = self.storage.upload_artifact(
                str(f),
                workflow_id=execution_id,
                node_id=node_id,
                artifact_type=artifact_type,
            )
            if minio_path:
                # Create DBFile record for this artifact (links MinIO to DB)
                new_file_id = self._create_db_file(
                    file_path=str(f),
                    minio_path=minio_path,
                )
                full_minio_url = f"minio://{self.storage.artifacts_bucket}/{minio_path}"
                uploaded[f.name] = (new_file_id, full_minio_url)
                # Map output keys to file_id so _update_output_data_fields
                # can proxy file_id alongside minio:// URL (critical for downstream nodes)
                for key in ["txt_path", "media_path", "latex_path", "pdf_path", "file_path"]:
                    field_file_ids[key] = new_file_id
                logger.info(
                    "node_output_file_uploaded",
                    execution_id=execution_id,
                    node_id=node_id,
                    filename=f.name,
                    minio_path=full_minio_url,
                    new_file_id=new_file_id,
                )

        if not uploaded:
            return output_data

        # Update output_data fields that point to container output paths
        result = self._update_output_data_fields(
            output_data, uploaded, temp_dir, field_file_ids
        )

        # Also update the on-disk output.json so the MinIO artifact upload below
        # picks up the correct paths
        with open(temp_dir / "output" / "output.json", "w", encoding="utf-8") as of:
            json.dump(result, of)

        return result

    def _update_output_data_fields(
        self,
        output_data: Dict[str, Any],
        uploaded: Dict[str, tuple[str, str]],
        temp_dir: Path,
        field_file_ids: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        """
        Update output_data fields that reference container output files.

        For each key in output_data that contains a container path (e.g. "/output/foo.m4a"),
        look up the corresponding uploaded file and replace with (new_file_id, minio_url).
        Also looks at the output directory for files that were created by the plugin.
        """
        import os
        output_dir = temp_dir / "output"
        result = {}
        for key, value in output_data.items():
            if value is None:
                result[key] = value
                continue
            value_str = str(value)
            matched = False
            if value_str.startswith(str(output_dir)) or value_str.startswith("/output/"):
                filename = os.path.basename(value_str)
                if filename in uploaded:
                    new_file_id, minio_url = uploaded[filename]
                    result[key] = minio_url
                    if key == "file_id" or "file_id" not in result:
                        result["file_id"] = new_file_id
                    matched = True
            if not matched:
                result[key] = value
        # Preserve file_id from original output_data if no upload match set it
        if "file_id" not in result and "file_id" in output_data:
            result["file_id"] = output_data["file_id"]

        # Proxy file_id alongside minio:// URL fields so downstream nodes
        # can download correctly (fixes: FileNotFoundError for txt_path/media_path/etc.)
        if field_file_ids:
            for key, new_file_id in field_file_ids.items():
                if result.get(key, "").startswith("minio://"):
                    result["file_id"] = new_file_id

        return result

    def _upload_node_logs(
        self,
        log_path: Path,
        execution_id: str,
        node_id: str,
        attempt: int = 1,
        log_type: str = "node",
    ) -> Optional[str]:
        """Сохраняет логи ноды в MinIO и удаляет локальную копию."""
        object_name = self.log_manager.save_logs_to_minio(
            log_path, execution_id, node_id, log_type=log_type, attempt=attempt
        )
        if object_name:
            self.log_manager.cleanup_local(log_path)
        return object_name
