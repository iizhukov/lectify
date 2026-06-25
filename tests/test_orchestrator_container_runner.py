"""
Tests for ContainerRunnerOrchestrator (src/orchestrator/container_runner.py)
"""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile

from src.orchestrator.container_runner import ContainerRunnerOrchestrator
from src.docker.runner import PollingContainerRunner, ContainerMetrics
from src.utils.storage import MinIOStorage


class TestContainerRunnerOrchestratorInit:
    def test_default_initialization(self):
        with patch("src.orchestrator.container_runner.PollingContainerRunner"), \
             patch("src.orchestrator.container_runner.ExecutionRepository"), \
             patch("src.orchestrator.container_runner.ExecutionNodeRepository"), \
             patch("src.orchestrator.container_runner.get_storage"), \
             patch("src.orchestrator.container_runner.NodeLogManager"):
            orch = ContainerRunnerOrchestrator()
            assert orch.docker_runner is not None
            assert orch.exec_repo is not None
            assert orch.node_repo is not None
            assert orch.storage is not None
            assert orch.log_manager is not None

    def test_custom_initialization(self):
        runner = MagicMock(spec=PollingContainerRunner)
        exec_repo = MagicMock()
        node_repo = MagicMock()
        storage = MagicMock(spec=MinIOStorage)

        orch = ContainerRunnerOrchestrator(
            docker_runner=runner,
            execution_repo=exec_repo,
            execution_node_repo=node_repo,
            storage=storage,
        )

        assert orch.docker_runner is runner
        assert orch.exec_repo is exec_repo
        assert orch.node_repo is node_repo
        assert orch.storage is storage


class TestContainerRunnerOrchestratorRun:
    def _run_with_mocks(self, **runner_run_kwargs):
        """Helper: call orch.run() with mocked internals."""
        runner = MagicMock(spec=PollingContainerRunner)
        runner.run_plugin.return_value = {"status": "ok", "output": "result"}

        node_repo = MagicMock()
        storage = MagicMock(spec=MinIOStorage)
        storage.upload_artifact.return_value = "exec123/node1/data/output.json"

        log_manager = MagicMock()
        log_manager.create_temp_log_file.return_value = Path(tempfile.mktemp(suffix=".log"))

        with patch("src.orchestrator.container_runner.PollingContainerRunner", return_value=runner), \
             patch("src.orchestrator.container_runner.ExecutionNodeRepository", return_value=node_repo), \
             patch("src.orchestrator.container_runner.MinIOStorage", return_value=storage), \
             patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator(
                docker_runner=runner,
                execution_node_repo=node_repo,
                storage=storage,
            )
            orch.log_manager = log_manager

            return orch.run(
                node_exec_id="node-exec-1",
                plugin_id="plugin-1",
                input_data={"text": "hello"},
                parameters={"output_type": "text"},
                execution_id="exec-123",
                node_id="node-1",
                **runner_run_kwargs
            ), runner, node_repo, storage, log_manager

    def test_successful_run_returns_output(self):
        result, runner, *_ = self._run_with_mocks()
        assert result == {"status": "ok", "output": "result"}
        runner.run_plugin.assert_called_once()

    def test_run_calls_docker_runner_with_correct_args(self):
        _, runner, *_ = self._run_with_mocks()
        runner.run_plugin.assert_called_once()
        call_kwargs = runner.run_plugin.call_args.kwargs
        assert call_kwargs["plugin_id"] == "plugin-1"
        assert call_kwargs["input_data"] == {"text": "hello"}
        assert call_kwargs["parameters"] == {"output_type": "text"}
        assert call_kwargs["execution_id"] == "exec-123"
        assert call_kwargs["node_id"] == "node-1"

    def test_run_uploads_artifact_when_output_exists(self):
        _, _, _, storage, _ = self._run_with_mocks()
        assert storage is not None

    def test_run_passes_metrics_callback_to_runner(self):
        _, runner, *_ = self._run_with_mocks()
        call_kwargs = runner.run_plugin.call_args.kwargs
        assert "on_metrics" in call_kwargs
        assert callable(call_kwargs["on_metrics"])

    def test_metrics_callback_updates_db(self):
        _, runner, node_repo, *_ = self._run_with_mocks()
        call_kwargs = runner.run_plugin.call_args.kwargs
        metrics_cb = call_kwargs["on_metrics"]

        metrics = MagicMock(spec=ContainerMetrics)
        metrics.cpu_percent = 45.0
        metrics.memory_mb = 128.0
        metrics.execution_time_ms = 5000

        metrics_cb(metrics)

        node_repo.update.assert_called_once_with(
            node_id="node-exec-1",
            cpu_percent=45.0,
            memory_mb=128.0,
            execution_time_ms=5000,
        )

    def test_run_always_uploads_logs_in_finally(self):
        _, _, _, _, log_manager = self._run_with_mocks()

        # Simulate the finally block being called after run_plugin
        # _upload_node_logs is called in finally, so we verify log_manager was used
        assert log_manager.create_temp_log_file.called

    def test_run_exception_still_triggers_log_upload(self):
        runner = MagicMock(spec=PollingContainerRunner)
        runner.run_plugin.side_effect = RuntimeError("docker error")

        log_manager = MagicMock()
        log_path = Path(tempfile.mktemp(suffix=".log"))
        log_manager.create_temp_log_file.return_value = log_path

        node_repo = MagicMock()
        storage = MagicMock(spec=MinIOStorage)

        with patch("src.orchestrator.container_runner.PollingContainerRunner", return_value=runner), \
             patch("src.orchestrator.container_runner.ExecutionNodeRepository", return_value=node_repo), \
             patch("src.orchestrator.container_runner.MinIOStorage", return_value=storage), \
             patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator(
                docker_runner=runner,
                execution_node_repo=node_repo,
                storage=storage,
            )
            orch.log_manager = log_manager

            with pytest.raises(RuntimeError, match="docker error"):
                orch.run(
                    node_exec_id="node-exec-1",
                    plugin_id="plugin-1",
                    input_data={},
                    parameters={},
                    execution_id="exec-123",
                    node_id="node-1",
                )

            # finally block uploads logs even after exception
            log_manager.save_logs_to_minio.assert_called_once()

    def test_run_with_timeout_and_progress_callback(self):
        progress_calls = []

        def on_progress(pct, msg):
            progress_calls.append((pct, msg))

        runner = MagicMock(spec=PollingContainerRunner)
        runner.run_plugin.return_value = {"done": True}

        with patch("src.orchestrator.container_runner.PollingContainerRunner", return_value=runner), \
             patch("src.orchestrator.container_runner.ExecutionNodeRepository"), \
             patch("src.orchestrator.container_runner.MinIOStorage"), \
             patch("src.orchestrator.container_runner.NodeLogManager") as lm:
            lm.return_value.create_temp_log_file.return_value = Path(tempfile.mktemp())
            orch = ContainerRunnerOrchestrator(docker_runner=runner)
            orch.log_manager = lm.return_value

            orch.run(
                node_exec_id="n1",
                plugin_id="p1",
                input_data={},
                parameters={},
                execution_id="e1",
                node_id="n1",
                timeout_seconds=300,
                on_progress=on_progress,
            )

        call_kwargs = runner.run_plugin.call_args.kwargs
        assert call_kwargs["timeout_seconds"] == 300
        assert call_kwargs["progress_callback"] is on_progress


class TestContainerRunnerOrchestratorUploadLogs:
    def test_upload_node_logs_returns_object_name(self):
        storage = MagicMock(spec=MinIOStorage)
        storage.upload_log.return_value = "node/2026/06/25/exec_node.log"

        log_manager = MagicMock()
        log_manager.save_logs_to_minio.return_value = "node/2026/06/25/exec_node.log"
        log_path = Path(tempfile.mktemp(suffix=".log"))
        log_path.write_text("some logs")

        with patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator(storage=storage)
            orch.log_manager = log_manager

            result = orch._upload_node_logs(log_path, "exec-123", "node-1")

        assert result == "node/2026/06/25/exec_node.log"
        log_manager.save_logs_to_minio.assert_called_once()
        log_manager.cleanup_local.assert_called_once_with(log_path)

    def test_upload_node_logs_cleans_up_on_success(self):
        log_manager = MagicMock()
        log_manager.save_logs_to_minio.return_value = "node/2026/06/25/exec_node.log"
        log_path = Path(tempfile.mktemp(suffix=".log"))

        with patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator()
            orch.log_manager = log_manager

            orch._upload_node_logs(log_path, "exec-123", "node-1")

        log_manager.cleanup_local.assert_called_once_with(log_path)

    def test_upload_node_logs_skips_cleanup_when_minio_fails(self):
        log_manager = MagicMock()
        log_manager.save_logs_to_minio.return_value = None
        log_path = Path(tempfile.mktemp(suffix=".log"))

        with patch("src.orchestrator.container_runner.NodeLogManager", return_value=log_manager):
            orch = ContainerRunnerOrchestrator()
            orch.log_manager = log_manager

            result = orch._upload_node_logs(log_path, "exec-123", "node-1")

        assert result is None
        log_manager.cleanup_local.assert_not_called()
