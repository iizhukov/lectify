"""
Tests for OrchestratorService: polling loop, execution, node run, retry logic.
"""
import asyncio
import concurrent.futures
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from collections import defaultdict

from src.orchestrator.service import (
    _topological_sort,
    _build_dependency_map,
    _map_inputs,
    _apply_transform,
    _is_non_retryable_error,
)


# ============================================================
# Pure function tests — topological sort
# ============================================================

class TestTopologicalSort:
    """Tests for _topological_sort (Kahn's algorithm)."""

    def test_single_node(self):
        """Single node with no edges."""
        nodes = [{"id": "a", "template_id": "t1"}]
        result = _topological_sort(nodes, [])
        assert [r["id"] for r in result] == ["a"]

    def test_linear_chain(self):
        """A → B → C (single path)."""
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [{"from_node_id": "a", "to_node_id": "b"}, {"from_node_id": "b", "to_node_id": "c"}]
        result_ids = [r["id"] for r in _topological_sort(nodes, edges)]
        assert result_ids.index("a") < result_ids.index("b") < result_ids.index("c")

    def test_parallel_branches(self):
        """A → B, A → C, B → D, C → D."""
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        edges = [
            {"from_node_id": "a", "to_node_id": "b"},
            {"from_node_id": "a", "to_node_id": "c"},
            {"from_node_id": "b", "to_node_id": "d"},
            {"from_node_id": "c", "to_node_id": "d"},
        ]
        result_ids = [r["id"] for r in _topological_sort(nodes, edges)]
        # a must come before both b and c
        assert result_ids.index("a") < result_ids.index("b")
        assert result_ids.index("a") < result_ids.index("c")
        # both b and c must come before d
        assert result_ids.index("b") < result_ids.index("d")
        assert result_ids.index("c") < result_ids.index("d")

    def test_diamond_graph(self):
        """A → B → D, A → C → D (diamond)."""
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        edges = [
            {"from_node_id": "a", "to_node_id": "b"},
            {"from_node_id": "a", "to_node_id": "c"},
            {"from_node_id": "b", "to_node_id": "d"},
            {"from_node_id": "c", "to_node_id": "d"},
        ]
        result_ids = [r["id"] for r in _topological_sort(nodes, edges)]
        assert result_ids.index("a") < result_ids.index("b")
        assert result_ids.index("a") < result_ids.index("c")
        assert result_ids.index("b") < result_ids.index("d")
        assert result_ids.index("c") < result_ids.index("d")

    def test_multiple_sources(self):
        """A, B both roots pointing to C."""
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [{"from_node_id": "a", "to_node_id": "c"}, {"from_node_id": "b", "to_node_id": "c"}]
        result_ids = [r["id"] for r in _topological_sort(nodes, edges)]
        assert result_ids.index("a") < result_ids.index("c")
        assert result_ids.index("b") < result_ids.index("c")

    def test_all_parallel_no_edges(self):
        """No edges — any order is fine."""
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = []
        result_ids = [r["id"] for r in _topological_sort(nodes, edges)]
        assert set(result_ids) == {"a", "b", "c"}

    def test_complex_dag(self):
        """Complex DAG: multiple layers."""
        nodes = [
            {"id": "src"},
            {"id": "t1"},
            {"id": "t2"},
            {"id": "merge"},
            {"id": "sink"},
        ]
        edges = [
            {"from_node_id": "src", "to_node_id": "t1"},
            {"from_node_id": "src", "to_node_id": "t2"},
            {"from_node_id": "t1", "to_node_id": "merge"},
            {"from_node_id": "t2", "to_node_id": "merge"},
            {"from_node_id": "merge", "to_node_id": "sink"},
        ]
        result_ids = [r["id"] for r in _topological_sort(nodes, edges)]
        assert result_ids.index("src") < result_ids.index("t1")
        assert result_ids.index("src") < result_ids.index("t2")
        assert result_ids.index("t1") < result_ids.index("merge")
        assert result_ids.index("t2") < result_ids.index("merge")
        assert result_ids.index("merge") < result_ids.index("sink")


# ============================================================
# Pure function tests — dependency map
# ============================================================

class TestBuildDependencyMap:
    def test_no_edges(self):
        nodes = [{"id": "a"}, {"id": "b"}]
        result = _build_dependency_map(nodes, [])
        assert result == {"a": [], "b": []}

    def test_chain(self):
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [{"from_node_id": "a", "to_node_id": "b"}, {"from_node_id": "b", "to_node_id": "c"}]
        result = _build_dependency_map(nodes, edges)
        assert result["a"] == []
        assert result["b"] == ["a"]
        assert result["c"] == ["b"]

    def test_parallel_merge(self):
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        edges = [{"from_node_id": "a", "to_node_id": "c"}, {"from_node_id": "b", "to_node_id": "c"}]
        result = _build_dependency_map(nodes, edges)
        assert set(result["c"]) == {"a", "b"}

    def test_unknown_node_in_edge_ignored(self):
        nodes = [{"id": "a"}]
        edges = [{"from_node_id": "a", "to_node_id": "unknown"}]
        result = _build_dependency_map(nodes, edges)
        assert result["a"] == []


# ============================================================
# Pure function tests — input mapping
# ============================================================

class TestMapInputs:
    def test___input_field_mapping(self):
        node_def = {
            "id": "b",
            "input_mapping": [
                {"source": "$__input.file_id", "target_field": "file_id"}
            ]
        }
        node_outputs = {"__input": {"file_id": "file-123"}}
        result = _map_inputs(node_def, [], node_outputs, "file-123")
        assert result == {"file_id": "file-123"}


# ============================================================
# Pure function tests — transform
# ============================================================

class TestApplyTransform:
    def test_passthrough(self):
        assert _apply_transform("hello", "passthrough") == "hello"
        assert _apply_transform(None, "passthrough") is None

    def test_to_string(self):
        assert _apply_transform(42, "string") == "42"
        assert _apply_transform(None, "string") == ""

    def test_to_int(self):
        assert _apply_transform("42", "int") == 42
        assert _apply_transform(3.14, "int") == 3
        assert _apply_transform(None, "int") == 0

    def test_to_float(self):
        assert _apply_transform("3.14", "float") == 3.14
        assert _apply_transform(None, "float") == 0.0

    def test_to_bool(self):
        assert _apply_transform(True, "bool") is True
        assert _apply_transform(False, "bool") is False
        assert _apply_transform("anything", "bool") is True


# ============================================================
# Pure function tests — non-retryable errors
# ============================================================

class TestIsNonRetryableError:
    def test_plugin_not_found(self):
        assert _is_non_retryable_error("Plugin not found") is True

    def test_image_not_found(self):
        assert _is_non_retryable_error("Image not found for node") is True

    def test_template_not_found(self):
        assert _is_non_retryable_error("template not found in registry") is True

    def test_input_file_not_found(self):
        assert _is_non_retryable_error("input file not found at /path") is True

    def test_retriable_error(self):
        assert _is_non_retryable_error("Connection timeout after 30s") is False

    def test_container_exited(self):
        assert _is_non_retryable_error("Container exited with code 1") is False

    def test_empty_error(self):
        assert _is_non_retryable_error("") is False


# ============================================================
# OrchestratorService integration unit tests (mocked I/O)
# ============================================================

@pytest.mark.asyncio
class TestOrchestratorServicePolling:
    """Test OrchestratorService polling loop behavior."""

    @pytest.fixture
    def mock_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig(
            enabled=True,
            max_concurrent_workflows=2,
            poll_interval_seconds=60,
            node_timeout_seconds=600,
            auto_retry_failed_nodes=False,
            max_node_retries=0,
        )
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            yield service

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, mock_service):
        """stop() should set _running to False."""
        mock_service._running = True
        await mock_service.stop()
        assert mock_service._running is False

    @pytest.mark.asyncio
    async def test_poll_skips_when_at_capacity(self, mock_service):
        """If _active_executions >= max_concurrent, no new tasks should be created."""
        mock_service._active_executions = {"exec-1", "exec-2"}
        mock_service.config.max_concurrent_workflows = 2

        created_tasks = []

        async def fake_run(exec_id):
            created_tasks.append(exec_id)

        mock_service._run_execution = fake_run
        mock_service.exec_repo.get_pending_executions = MagicMock(return_value=[
            MagicMock(id="exec-3"),
        ])

        await mock_service._poll_and_launch()
        assert created_tasks == []


@pytest.mark.asyncio
class TestOrchestratorServiceExecution:
    """Test _run_execution workflow execution."""

    @pytest.fixture
    def mock_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig(
            enabled=True,
            max_concurrent_workflows=3,
            poll_interval_seconds=60,
            node_timeout_seconds=600,
            auto_retry_failed_nodes=False,
            max_node_retries=0,
        )
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            yield service

    @pytest.mark.asyncio
    async def test_execution_not_found(self, mock_service):
        """If execution not in DB, _run_execution returns early."""
        mock_service.exec_repo.get.return_value = None
        mock_service.exec_repo.update_status = MagicMock()

        await mock_service._run_execution("nonexistent-id")
        mock_service.exec_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_node_failure_stops_execution(self, mock_service):
        """If _run_node returns False, execution status should be FAILED."""
        execution = MagicMock()
        execution.id = "exec-1"
        execution.workflow_template_id = "wf-1"
        execution.file_id = "file-1"
        execution.nodes = [MagicMock(node_id="n1")]

        workflow = MagicMock()
        workflow.graph = {
            "nodes": [{"id": "n1", "plugin_id": "t1"}],
            "edges": [],
        }

        mock_service.exec_repo.get.return_value = execution
        mock_service.workflow_repo.get.return_value = workflow
        mock_service.exec_repo.update_status = MagicMock()

        async def failing_node(**kwargs):
            return False

        mock_service._run_node = failing_node

        await mock_service._run_execution("exec-1")

        statuses = [call[0][1] for call in mock_service.exec_repo.update_status.call_args_list]
        assert statuses[-1].value == "failed"

    @pytest.mark.asyncio
    async def test_active_executions_cleaned_up_on_success(self, mock_service):
        """_active_executions should be cleaned up after success."""
        execution = MagicMock()
        execution.id = "exec-1"
        execution.workflow_template_id = "wf-1"
        execution.file_id = "file-1"
        execution.nodes = []

        workflow = MagicMock()
        workflow.graph = {
            "nodes": [{"id": "n1", "plugin_id": "t1"}],
            "edges": [],
        }

        mock_service.exec_repo.get.return_value = execution
        mock_service.workflow_repo.get.return_value = workflow
        mock_service.exec_repo.update_status = MagicMock()

        async def noop(**kwargs):
            return True

        mock_service._run_node = noop

        mock_service._active_executions.add("exec-1")
        await mock_service._run_execution("exec-1")
        assert "exec-1" not in mock_service._active_executions

    @pytest.mark.asyncio
    async def test_active_executions_cleaned_up_on_failure(self, mock_service):
        """_active_executions should be cleaned up after failure."""
        execution = MagicMock()
        execution.id = "exec-1"
        execution.workflow_template_id = "wf-1"
        execution.file_id = "file-1"
        execution.nodes = []

        workflow = MagicMock()
        workflow.graph = {
            "nodes": [{"id": "n1", "plugin_id": "t1"}],
            "edges": [],
        }

        mock_service.exec_repo.get.return_value = execution
        mock_service.workflow_repo.get.return_value = workflow
        mock_service.exec_repo.update_status = MagicMock()

        async def failing(**kwargs):
            raise RuntimeError("boom")

        mock_service._run_node = failing

        mock_service._active_executions.add("exec-1")
        await mock_service._run_execution("exec-1")
        assert "exec-1" not in mock_service._active_executions


@pytest.mark.asyncio
class TestOrchestratorServiceNodeRun:
    """Test _run_node retry and error handling."""

    @pytest.fixture
    def mock_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig(
            enabled=True,
            max_concurrent_workflows=3,
            poll_interval_seconds=60,
            node_timeout_seconds=600,
            auto_retry_failed_nodes=True,
            max_node_retries=2,
        )
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            yield service

    def _mock_node(self, plugin_id="media_converter", parameters=None):
        node = MagicMock()
        node.plugin_id = plugin_id
        node.parameters = parameters or {}
        return node

    def _mock_node_exec(self):
        return MagicMock(id="nexec-1")

    @pytest.mark.asyncio
    async def test_node_success(self, mock_service):
        """On successful container run, node status should be COMPLETED."""
        mock_service.node_repo.get.return_value = self._mock_node()
        mock_service.node_repo.update = MagicMock()
        mock_service.container_runner.run.return_value = {"result": "ok"}

        result = await mock_service._run_node(
            execution_id="exec-1",
            node_exec=self._mock_node_exec(),
            node_def={"id": "n1", "plugin_id": "t1"},
            input_data={},
        )

        assert result == {'result': 'ok'}
        update_calls = mock_service.node_repo.update.call_args_list
        last_call = update_calls[-1]
        assert last_call[1]["status"].value == "completed"

    @pytest.mark.asyncio
    async def test_node_retries_on_failure(self, mock_service):
        """Node should retry on transient errors up to max_retries."""
        mock_service.node_repo.get.return_value = self._mock_node()
        mock_service.node_repo.update = MagicMock()
        # Fail twice, then succeed
        mock_service.container_runner.run.side_effect = [
            RuntimeError("transient error"),
            RuntimeError("transient error"),
            {"result": "ok"},
        ]
        mock_service.config.auto_retry_failed_nodes = True
        mock_service.config.max_node_retries = 2

        result = await mock_service._run_node(
            execution_id="exec-1",
            node_exec=self._mock_node_exec(),
            node_def={"id": "n1", "plugin_id": "t1"},
            input_data={},
        )

        assert result == {'result': 'ok'}
        assert mock_service.container_runner.run.call_count == 3


@pytest.mark.asyncio
class TestOrchestratorServiceResume:
    """Test _resume_interrupted."""

    @pytest.fixture
    def mock_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig(
            enabled=True,
            max_concurrent_workflows=3,
            poll_interval_seconds=60,
            node_timeout_seconds=600,
            auto_retry_failed_nodes=False,
            max_node_retries=0,
        )
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            yield service

    @pytest.mark.asyncio
    async def test_resume_running_executions(self, mock_service):
        """Running executions from before restart should be resumed."""
        mock_service.exec_repo.get_running_executions = MagicMock(return_value=[
            MagicMock(id="running-1"),
            MagicMock(id="running-2"),
        ])

        launched = []

        async def fake_run(exec_id):
            launched.append(exec_id)

        mock_service._run_execution = fake_run

        executor = concurrent.futures.ThreadPoolExecutor()
        task_futures = []
        loop = asyncio.get_event_loop()

        def capture_task(coro, **kwargs):
            fut = loop.create_future()

            def run():
                try:
                    result = asyncio.run(coro)
                    loop.call_soon_threadsafe(fut.set_result, result)
                except Exception as e:
                    loop.call_soon_threadsafe(fut.set_exception, e)

            executor.submit(run)
            task_futures.append(fut)
            return MagicMock()

        with patch("asyncio.create_task", side_effect=capture_task):
            await mock_service._resume_interrupted()

        await asyncio.gather(*task_futures)
        assert set(launched) == {"running-1", "running-2"}

    @pytest.mark.asyncio
    async def test_resume_skips_already_active(self, mock_service):
        """Executions already in _active_executions should not be re-launched."""
        mock_service.exec_repo.get_running_executions = MagicMock(return_value=[
            MagicMock(id="already-active"),
        ])
        mock_service._active_executions.add("already-active")

        launched = []

        async def fake_run(exec_id):
            launched.append(exec_id)

        mock_service._run_execution = fake_run

        await mock_service._resume_interrupted()
        assert launched == []
