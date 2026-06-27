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

            log_manager.save_logs_to_minio.assert_called_once()


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
