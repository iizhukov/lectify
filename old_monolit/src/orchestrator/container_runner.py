"""
Container Runner для оркестратора.
Оборачивает PollingContainerRunner и добавляет:
- Сохранение артефактов в MinIO
- Создание DBFile для каждого загруженного артефакта (для связи с БД)
- Сохранение логов в MinIO
- Обновление метрик ноды в БД
"""
import os
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.docker.runner import PollingContainerRunner, ContainerMetrics, cleanup_temp_files
from src.db.repository import ExecutionRepository, ExecutionNodeRepository
from src.db.database import SessionLocal
from src.db.entity import DBFile
from src.utils.storage import MinIOStorage, get_storage
from src.orchestrator.logs import NodeLogManager
from src.orchestrator.input_resolver import InputResolver
from src.plugins.registry import PluginRegistry
from src.utils.logging import get_logger
from src.utils.metrics import get_metrics


logger = get_logger(__name__)


def _parse_prometheus_text(text: str) -> Dict[str, list[Dict]]:
    metrics: Dict[str, list[Dict]] = {}
    for line in text.split("\n"):
        line = line.strip()

        if not line or line.startswith("#"):
            continue
        try:
            if "{" in line:
                metric_part, value_part = line.rsplit(" ", 1)
                metric_name, labels_str = metric_part.split("{", 1)
                labels_str = labels_str.rstrip("}")
                labels = {}

                for label_pair in labels_str.split(","):
                    if "=" in label_pair:
                        key, val = label_pair.split("=", 1)
                        labels[key.strip()] = val.strip('"')

                if metric_name not in metrics:
                    metrics[metric_name] = []

                metrics[metric_name].append({"labels": labels, "value": float(value_part)})
        except Exception:
            continue

    return metrics


def _parameters_for_artifact_type(ext: str) -> str:
    mapping = {
        "m4a": "audio", "mp3": "audio", "wav": "audio", "ogg": "audio",
        "mp4": "video", "mkv": "video", "avi": "video", "mov": "video",
        "txt": "text", "md": "text", "tex": "text",
        "pdf": "pdf",
    }
    return mapping.get(ext.lower(), "data")


def _replace_paths_in_dict(data: Any, uploaded: Dict[str, str]) -> Any:
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

        plugin_cls = PluginRegistry().get_plugin(plugin_id)
        if plugin_cls:
            resolver = InputResolver(self.storage)
            manifest, extra_input = resolver.resolve(plugin_cls(), input_data, temp_dir, parameters)

            manifest_path = temp_dir / "input" / ".manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest._to_manifest_dict()), encoding="utf-8")

            input_data = {**input_data, **extra_input}

        output_file = temp_dir / "output" / "output.json"

        effective_log_type = log_type or plugin_id
        log_path = self.log_manager.create_temp_log_file(execution_id, node_id)

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

            self._forward_plugin_metrics(temp_dir, plugin_id, execution_id)

            output_artifacts = getattr(plugin_cls, "output_artifacts", {}) if plugin_cls else {}

            if not isinstance(output_artifacts, dict):
                output_artifacts = {}

            output_data = self._upload_output_files(
                output_data, temp_dir, execution_id, node_id, output_artifacts
            )

            logger.info(
                f"_upload_output_files_result "
                f"execution_id={execution_id} node_id={node_id} "
                f"output_data_keys={list(output_data.keys()) if output_data else None} "
                f"txt_path={output_data.get('txt_path') if output_data else None} "
                f"file_id={output_data.get('file_id') if output_data else None}"
            )

            if output_data and not output_file.exists():
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(output_data, f)

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
            self._metrics.node_cpu_percent.labels(node_id=node_id).set(0)
            self._metrics.node_memory_mb.labels(node_id=node_id).set(0)

            minio_logs_path = self._upload_node_logs(log_path, execution_id, node_id, attempt=attempt, log_type=effective_log_type)
            if minio_logs_path:
                self.node_repo.update(node_id=node_exec_id, logs_path=minio_logs_path)

            cleanup_temp_files(execution_id, node_id)

    def _create_db_file(
        self,
        file_path: str,
        minio_path: str,
    ) -> str:
        

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
        output_artifacts: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if output_data is None:
            return {}

        output_dir = temp_dir / "output"
        if not output_dir.exists():
            logger.warning(
                "output_dir_missing",
                execution_id=execution_id,
                node_id=node_id,
                output_dir=str(output_dir),
            )
            return output_data

        output_artifacts = output_artifacts or {}

        uploaded: dict[str, tuple[str, str]] = {}
        target_fields: dict[str, str] = {}

        for name, source in output_artifacts.items():
            if isinstance(source, dict):
                filename = source.get("filename")
                target_field = source.get("target_field")
            else:
                filename = getattr(source, "filename", None)
                target_field = getattr(source, "target_field", None)

            if not filename:
                continue

            file_path = output_dir / filename
            if not file_path.exists():
                logger.warning(
                    "output_artifact_missing",
                    execution_id=execution_id,
                    node_id=node_id,
                    artifact_name=name,
                    filename=filename,
                )

                continue

            ext = file_path.suffix.lstrip(".")
            artifact_type = _parameters_for_artifact_type(ext)
            minio_path = self.storage.upload_artifact(
                str(file_path),
                workflow_id=execution_id,
                node_id=node_id,
                artifact_type=artifact_type,
            )

            if minio_path:
                new_file_id = self._create_db_file(
                    file_path=str(file_path),
                    minio_path=minio_path,
                )

                full_minio_url = f"minio://{self.storage.artifacts_bucket}/{minio_path}"
                uploaded[filename] = (new_file_id, full_minio_url)

                if target_field:
                    target_fields[name] = target_field

                logger.info(
                    "node_output_file_uploaded",
                    execution_id=execution_id,
                    node_id=node_id,
                    filename=filename,
                    minio_path=full_minio_url,
                    new_file_id=new_file_id,
                )

        if not uploaded:
            return output_data

        result = self._update_output_data_fields(
            output_data, uploaded, temp_dir
        )

        for artifact_name, field_name in target_fields.items():
            if not result.get(field_name):
                for filename, (new_file_id, _) in uploaded.items():
                    src = output_artifacts.get(artifact_name)
                    artifact_filename = src.get("filename") if isinstance(src, dict) else getattr(src, "filename", None) if src else None

                    if artifact_filename == filename:
                        result[field_name] = new_file_id
                        logger.info(
                            "output_field_injected",
                            execution_id=execution_id,
                            node_id=node_id,
                            field=field_name,
                            file_id=new_file_id,
                            filename=filename,
                        )
                        break

        with open(temp_dir / "output" / "output.json", "w", encoding="utf-8") as of:
            json.dump(result, of)

        return result

    def _update_output_data_fields(
        self,
        output_data: Dict[str, Any],
        uploaded: Dict[str, tuple[str, str]],
        temp_dir: Path,
    ) -> Dict[str, Any]:
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

                    if "file_id" not in result:
                        result["file_id"] = new_file_id

                    matched = True

            if not matched:
                result[key] = value

        if "file_id" not in result:
            result["file_id"] = output_data.get("file_id", "")

        return result

    def _forward_plugin_metrics(
        self,
        temp_dir: Path,
        plugin_id: str,
        execution_id: str,
    ):
        metrics_file = temp_dir / "output" / "metrics.json"
        if not metrics_file.exists():
            return

        try:
            text = metrics_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("failed_to_read_plugin_metrics_file", error=str(e))
            return

        parsed = _parse_prometheus_text(text)
        if not parsed:
            return

        m = get_metrics()
        for entry in parsed.get("lectify_llm_api_requests_total", []):
            purpose = entry["labels"].get("purpose", "unknown")
            status = entry["labels"].get("status", "unknown")
            m.llm_api_requests.labels(purpose=purpose, status=status).inc(int(entry["value"]))

        for entry in parsed.get("lectify_llm_api_duration_seconds", []):
            purpose = entry["labels"].get("purpose", "unknown")
            m.llm_api_duration.labels(purpose=purpose).observe(entry["value"])

        for entry in parsed.get("lectify_llm_api_errors_total", []):
            purpose = entry["labels"].get("purpose", "unknown")
            error_type = entry["labels"].get("error_type", "unknown")
            m.llm_api_errors.labels(purpose=purpose, error_type=error_type).inc(int(entry["value"]))

        logger.info(
            "plugin_metrics_forwarded",
            plugin_id=plugin_id,
            execution_id=execution_id,
            metric_names=list(parsed.keys()),
        )

    def _upload_node_logs(
        self,
        log_path: Path,
        execution_id: str,
        node_id: str,
        attempt: int = 1,
        log_type: str = "node",
    ) -> Optional[str]:
        object_name = self.log_manager.save_logs_to_minio(
            log_path, execution_id, node_id, log_type=log_type, attempt=attempt
        )

        if object_name:
            self.log_manager.cleanup_local(log_path)
        
        return object_name
