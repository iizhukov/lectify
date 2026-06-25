"""
Container Runner — manages plugin execution in Docker containers
"""

import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

if TYPE_CHECKING:
    from src.docker.client import DockerClient

from src.docker.client import DockerClient, get_docker_client

logger = logging.getLogger(__name__)


class ContainerMetrics:
    """Metrics collected during container execution"""

    def __init__(self):
        self.cpu_percent: float = 0
        self.memory_mb: float = 0
        self.execution_time_ms: int = 0
        self.logs: str = ""


class ContainerRunner:
    """
    Runs a plugin inside an isolated Docker container.

    Lifecycle:
    1. Create input.json in MinIO
    2. Start container with volume mount
    3. Poll stats + logs every 1 second
    4. Update progress via callback
    5. Read output.json from MinIO
    6. Stop and remove container
    """

    def __init__(
        self,
        docker_client: Optional["DockerClient"] = None,
        minio_client: Any = None
    ):
        self.docker = docker_client or get_docker_client()
        self.minio_client = minio_client

    def run_plugin(
        self,
        plugin_id: str,
        input_data: Dict[str, Any],
        parameters: Dict[str, Any],
        execution_id: str,
        node_id: str,
        progress_callback: Callable[[int, str], None] | None = None,
        timeout_seconds: int = 300,
        on_cleanup: Callable[[], None] | None = None,
        on_metrics: Callable[["ContainerMetrics"], None] | None = None,
    ) -> Dict[str, Any]:
        """
        Run a plugin in a Docker container.

        Args:
            on_cleanup: called in finally block, before temp file cleanup.
                        Use to persist logs/artifacts before they are deleted.
            on_metrics: called with updated ContainerMetrics every polling interval.
        Returns output data dict.
        """
        container_id = None
        start_time = time.time()

        try:
            # 1. Prepare input
            progress_callback(5, "Подготовка данных...") if progress_callback else None

            input_key = self._write_input_to_temp(
                plugin_id, execution_id, node_id, input_data, parameters
            )

            # 2. Build/start container
            if progress_callback:
                progress_callback(10, "Запуск контейнера...")

            image_name = f"lectify-plugin-{plugin_id}"
            container_id = self._start_container(
                image_name,
                execution_id,
                node_id,
                input_key
            )

            if not container_id:
                raise Exception(f"Failed to start container for plugin {plugin_id}")

            if progress_callback:
                progress_callback(15, "Выполнение...")

            # 3. Poll until completion
            metrics = ContainerMetrics()
            last_status_check = 0
            status_check_interval = 1.0  # Check every 1 second

            while True:
                elapsed_sec = time.time() - start_time
                if elapsed_sec > timeout_seconds:
                    raise TimeoutError(f"Plugin execution timed out after {timeout_seconds}s")

                # Check container status
                container = self.docker.get_container(container_id)
                if not container:
                    raise Exception("Container disappeared")

                status = container.status

                if status == "exited":
                    # Container finished
                    exit_code = container.attrs.get("State", {}).get("ExitCode", 0)
                    logs = self.docker.get_container_logs(container_id)

                    if exit_code != 0:
                        raise Exception(f"Plugin failed with exit code {exit_code}\n{logs}")

                    break

                # Poll metrics every status_check_interval seconds
                if time.time() - last_status_check >= status_check_interval:
                    stats = self.docker.get_container_stats(container_id)
                    if stats:
                        metrics.cpu_percent = stats["cpu_percent"]
                        metrics.memory_mb = stats["memory_mb"]

                    metrics.logs = self.docker.get_container_logs(container_id)

                    # Update progress based on time
                    progress = min(15 + int((elapsed_sec / timeout_seconds) * 80), 95)
                    progress_callback(
                        progress,
                        f"Выполняется... CPU: {metrics.cpu_percent:.0f}%, RAM: {metrics.memory_mb:.0f}MB"
                    ) if progress_callback else None

                    last_status_check = time.time()

                time.sleep(0.5)

            # 4. Read output
            if progress_callback:
                progress_callback(95, "Чтение результата...")
            output_data = self._read_output_from_temp(execution_id, node_id)

            metrics.execution_time_ms = int((time.time() - start_time) * 1000)

            if progress_callback:
                progress_callback(100, "Готово!")

            return output_data

        except Exception as e:
            logger.error(f"Plugin {plugin_id} failed: {e}")
            if progress_callback:
                progress_callback(100, f"Ошибка: {str(e)}")
            raise

        finally:
            # 5. Cleanup
            if container_id:
                self.docker.stop_container(container_id, timeout=5)
                self.docker.remove_container(container_id, force=True)

            # Persist logs/artifacts before cleaning up temp files
            if on_cleanup is not None:
                on_cleanup()

            # Cleanup temp files
            self._cleanup_temp_files(execution_id, node_id)

    def _write_input_to_temp(
        self,
        plugin_id: str,
        execution_id: str,
        node_id: str,
        input_data: Dict[str, Any],
        parameters: Dict[str, Any]
    ) -> str:
        """Write input.json to temp directory"""
        temp_dir = Path(tempfile.gettempdir()) / "lectify"
        temp_dir.mkdir(exist_ok=True)

        node_dir = temp_dir / execution_id / node_id
        node_dir.mkdir(parents=True, exist_ok=True)

        input_file = node_dir / "input.json"

        # Add plugin metadata
        full_input = {
            **input_data,
            "__plugin_id": plugin_id,
            "__parameters": parameters,
            "execution_id": execution_id,
            "node_id": node_id
        }

        with open(input_file, "w") as f:
            json.dump(full_input, f)

        return str(input_file)

    def _start_container(
        self,
        image_name: str,
        execution_id: str,
        node_id: str,
        input_path: str
    ) -> Optional[str]:
        """Start container with plugin image"""
        temp_dir = Path(tempfile.gettempdir()) / "lectify"
        node_dir = temp_dir / execution_id / node_id

        environment = {
            "PLUGIN_INPUT": "/input/input.json",
            "PLUGIN_OUTPUT": "/output/output.json"
        }

        # Keys = container paths (docker-py convention), values = host path + mode
        volumes = {
            "/input": {"bind": str(node_dir), "mode": "ro"},
            "/output": {"bind": str(node_dir), "mode": "rw"},
        }

        container = self.docker.create_container(
            image=image_name,
            command="python -m src.plugins.runner",
            volumes=volumes,
            environment=environment,
            mem_limit="1g",
            cpu_quota=50000  # 50% CPU
        )

        return container.id if container else None

    def _read_output_from_temp(
        self,
        execution_id: str,
        node_id: str
    ) -> Dict[str, Any]:
        """Read output.json from temp directory"""
        temp_dir = Path(tempfile.gettempdir()) / "lectify"
        node_dir = temp_dir / execution_id / node_id
        output_file = node_dir / "output.json"

        if not output_file.exists():
            raise FileNotFoundError(f"Output file not found: {output_file}")

        with open(output_file, "r") as f:
            return json.load(f)

    def _cleanup_temp_files(self, execution_id: str, node_id: str):
        """Remove temp files"""
        try:
            temp_dir = Path(tempfile.gettempdir()) / "lectify"
            node_dir = temp_dir / execution_id / node_id

            if node_dir.exists():
                import shutil
                shutil.rmtree(node_dir)
        except Exception as e:
            logger.warning(f"Failed to cleanup temp files: {e}")


class PollingContainerRunner(ContainerRunner):
    """
    ContainerRunner with metrics polling via threading.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_polling = threading.Event()
        self._latest_metrics: Optional[ContainerMetrics] = None

    def run_plugin(
        self,
        plugin_id: str,
        input_data: Dict[str, Any],
        parameters: Dict[str, Any],
        execution_id: str,
        node_id: str,
        progress_callback: Callable[[int, str], None] | None = None,
        timeout_seconds: int = 300,
        on_cleanup: Callable[[], None] | None = None,
        on_metrics: Callable[["ContainerMetrics"], None] | None = None,
    ) -> Dict[str, Any]:
        """
        Run plugin with continuous metrics polling.
        """
        container_id = None
        start_time = time.time()
        self._latest_metrics = ContainerMetrics()
        self._stop_polling.clear()

        try:
            # Prepare input
            if progress_callback:
                progress_callback(5, "Подготовка...")

            input_path = self._write_input_to_temp(
                plugin_id, execution_id, node_id, input_data, parameters
            )

            # Start container
            if progress_callback:
                progress_callback(10, "Запуск...")

            image_name = f"lectify-plugin-{plugin_id}"
            container_id = self._start_container(
                image_name, execution_id, node_id, input_path
            )

            if not container_id:
                raise Exception(f"Failed to start container for {plugin_id}")

            # Start polling thread
            self._poll_thread = threading.Thread(
                target=self._poll_metrics,
                args=(container_id, start_time, progress_callback, on_metrics),
                daemon=True
            )
            self._poll_thread.start()

            # Wait for completion
            return self._wait_for_completion(
                container_id,
                execution_id,
                node_id,
                progress_callback,
                timeout_seconds
            )

        finally:
            self._stop_polling.set()
            if container_id:
                self.docker.stop_container(container_id, timeout=5)
                self.docker.remove_container(container_id, force=True)
            if on_cleanup is not None:
                on_cleanup()
            self._cleanup_temp_files(execution_id, node_id)

    def _poll_metrics(
        self,
        container_id: str,
        start_time: float,
        progress_callback: Callable,
        on_metrics: Callable
    ):
        """Poll metrics in background thread"""
        while not self._stop_polling.is_set():
            container = self.docker.get_container(container_id)
            if not container:
                break

            if container.status in ["exited", "dead"]:
                break

            stats = self.docker.get_container_stats(container_id)
            if stats and self._latest_metrics:
                self._latest_metrics.cpu_percent = stats["cpu_percent"]
                self._latest_metrics.memory_mb = stats["memory_mb"]
                self._latest_metrics.execution_time_ms = int(
                    (time.time() - start_time) * 1000
                )

            if on_metrics is not None and self._latest_metrics is not None:
                on_metrics(self._latest_metrics)

            self._stop_polling.wait(timeout=1.0)

        # Final log fetch
        if self._latest_metrics is not None:
            self._latest_metrics.logs = self.docker.get_container_logs(container_id)

    def _wait_for_completion(
        self,
        container_id: str,
        execution_id: str,
        node_id: str,
        progress_callback: Callable[[int, str], None] | None,
        timeout_seconds: int
    ) -> Dict[str, Any]:
        """Wait for container to complete"""
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(f"Execution timed out after {timeout_seconds}s")

            container = self.docker.get_container(container_id)
            if not container:
                raise Exception("Container disappeared")

            status = container.status

            if status == "exited":
                exit_code = container.attrs.get("State", {}).get("ExitCode", 0)

                if exit_code != 0:
                    logs = self.docker.get_container_logs(container_id)
                    raise Exception(f"Plugin failed (exit {exit_code}):\n{logs}")

                if progress_callback:
                    progress_callback(95, "Чтение результата...")
                return self._read_output_from_temp(execution_id, node_id)

            # Update progress
            progress = min(15 + int((elapsed / timeout_seconds) * 80), 95)
            m = self._latest_metrics
            if m and progress_callback:
                progress_callback(
                    progress,
                    f"CPU: {m.cpu_percent:.0f}%, RAM: {m.memory_mb:.0f}MB"
                )

            time.sleep(0.5)
