import tempfile
from pathlib import Path
from typing import Optional

from src.utils.storage import MinIOStorage, get_storage
from src.utils.logging import get_logger

logger = get_logger(__name__)


class NodeLogManager:
    def __init__(self, storage: MinIOStorage | None = None):
        self.storage = storage or get_storage()

    def create_temp_log_file(self, execution_id: str, node_id: str) -> Path:
        log_dir = Path(tempfile.gettempdir()) / "lectify" / "logs" / execution_id / node_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "node.log"
        log_path.touch()

        return log_path

    def append_logs(self, log_path: Path, new_logs: str) -> None:
        if not new_logs:
            return
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(new_logs)
        except Exception as e:
            logger.warning("failed_to_append_logs", path=str(log_path), error=str(e))

    def save_logs_to_minio(
        self,
        log_path: Path,
        execution_id: str,
        node_id: str,
        log_type: str = "node",
        attempt: int = 1,
    ) -> Optional[str]:
        if not log_path.exists() or log_path.stat().st_size == 0:
            logger.debug("no_logs_to_upload", execution_id=execution_id, node_id=node_id)
            return None

        object_name = self.storage.upload_log(
            str(log_path),
            execution_id=execution_id,
            attempt=attempt,
            log_type=log_type,
        )

        if object_name:
            logger.info(
                "node_logs_saved_to_minio",
                execution_id=execution_id,
                node_id=node_id,
                attempt=attempt,
                object_name=object_name,
                size_bytes=log_path.stat().st_size
            )

        return object_name

    def get_logs(self, execution_id: str, node_id: str, log_type: str = "node", attempt: int = 1) -> Optional[str]:
        object_name = f"executions/{execution_id}/{attempt}/{log_type}/node.log"
        return self.storage.read_log(object_name)

    def cleanup_local(self, log_path: Path) -> None:
        try:
            if log_path.exists():
                log_path.unlink()
                logger.debug("local_log_removed", path=str(log_path))
        except Exception as e:
            logger.warning("failed_to_cleanup_log", path=str(log_path), error=str(e))
