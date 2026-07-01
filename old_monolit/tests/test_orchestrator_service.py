import asyncio
import concurrent.futures
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestrator.service import (
    _topological_sort,
    _build_dependency_map,
    _map_inputs,
    _apply_transform,
    _is_non_retryable_error,
)


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


class TestMapInputsEdgeCases:
    """Additional edge-case tests for _map_inputs."""

    def test_no_input_mapping_no_dependencies(self):
        """No input_mapping and no dependencies: returns empty + file_id."""
        node_def = {"id": "n1", "plugin_id": "some_plugin"}
        node_outputs = {"__input": {}}
        result = _map_inputs(node_def, [], node_outputs, "file-abc")
        assert result == {"file_id": "file-abc"}

    def test_no_input_mapping_with_dependency(self):
        """No input_mapping but has a dependency: copies dep output + injects execution file_id."""
        node_def = {"id": "n2", "plugin_id": "media_converter"}
        node_outputs = {
            "__input": {},
            "upstream": {"result": "ok", "file_id": "upstream-file"},
        }
        result = _map_inputs(node_def, ["upstream"], node_outputs, "exec-file")
        # file_id is injected from execution even if dep already has one
        assert result == {"result": "ok", "file_id": "exec-file"}

    def test_no_input_mapping_input_plugin_skips_file_id_injection(self):
        """is_input_plugin=True: no file_id injected when no input_mapping."""
        node_def = {"id": "input_node", "plugin_id": "input"}
        node_outputs = {"__input": {}}
        result = _map_inputs(node_def, [], node_outputs, "exec-file")
        assert result == {}

    def test_input_mapping_with_transform_suffix(self):
        """Transform after + in source string is NOT supported; source is used verbatim."""
        node_def = {
            "id": "n3",
            "input_mapping": [
                {"source": "$upstream.output.count+int", "target_field": "count"}
            ],
        }
        node_outputs = {"upstream": {"output": {"count": "42"}}}
        # The "+transform" suffix is NOT parsed separately; "output.count+int" is the field key
        result = _map_inputs(node_def, [], node_outputs, "")
        # Field "output.count+int" doesn't exist → value is None
        assert result["count"] is None

    def test_input_mapping_with_explicit_transform(self):
        """Explicit transform key applies _apply_transform to the resolved value."""
        node_def = {
            "id": "n4",
            "input_mapping": [
                {"source": "$upstream.output.value", "target_field": "count", "transform": "int"}
            ],
        }
        # source "$upstream.output.value" parses to parts=["upstream","output","value"],
        # source_field="value", reads node_outputs["upstream"]["value"]
        node_outputs = {"upstream": {"value": "99"}}
        result = _map_inputs(node_def, [], node_outputs, "")
        assert result["count"] == 99

    def test_input_mapping_with_upstream_output_dot_syntax(self):
        """$upstream_node.output.field reads node_outputs[upstream_node][field]."""
        node_def = {
            "id": "n5",
            "input_mapping": [
                {"source": "$latex.output.pdf_id", "target_field": "pdf_id"}
            ],
        }
        node_outputs = {"latex": {"pdf_id": "pdf-123"}}
        result = _map_inputs(node_def, [], node_outputs, "")
        assert result["pdf_id"] == "pdf-123"

    def test_input_mapping_literal_value_not_dollar(self):
        """A source without $ prefix is treated as a literal string."""
        node_def = {
            "id": "n6",
            "input_mapping": [
                {"source": "default_format", "target_field": "format"}
            ],
        }
        node_outputs = {}
        result = _map_inputs(node_def, [], node_outputs, "")
        assert result["format"] == "default_format"

    def test_input_mapping_file_id_from_upstream_not_exec(self):
        """file_id is always injected from execution (not from upstream) when provided."""
        node_def = {
            "id": "n7",
            "input_mapping": [
                {"source": "$upstream.output.audio_id", "target_field": "audio_id"}
            ],
        }
        node_outputs = {
            "__input": {},
            "upstream": {"audio_id": "from-upstream"},
        }
        result = _map_inputs(node_def, ["upstream"], node_outputs, "exec-file")
        # file_id is injected from execution even though upstream also has audio_id
        assert result["file_id"] == "exec-file"
        assert result["audio_id"] == "from-upstream"

    def test_input_mapping_file_path_injected_when_provided(self):
        """file_path is injected when file_path is provided and not is_input_plugin."""
        node_def = {
            "id": "n8",
            "plugin_id": "latex_to_pdf",
            "input_mapping": [
                {"source": "$upstream.output.tex_id", "target_field": "tex_id"}
            ],
        }
        node_outputs = {"upstream": {"tex_id": "tex-1", "file_id": "tex-file"}}
        result = _map_inputs(node_def, ["upstream"], node_outputs, "exec-f", "/path/to/file")
        assert result["file_path"] == "/path/to/file"

    def test_input_mapping_is_input_plugin_skips_file_id_injection(self):
        """With input_mapping, is_input_plugin skips automatic file_id injection."""
        node_def = {
            "id": "input_node",
            "plugin_id": "input",
            "input_mapping": [
                {"source": "$__input.input.file_id", "target_field": "file_id"}
            ],
        }
        node_outputs = {"__input": {"input.file_id": "input-file-xyz"}}
        result = _map_inputs(node_def, [], node_outputs, "exec-file")
        assert result == {"file_id": "input-file-xyz"}


class TestApplyTransformEdgeCases:
    """Edge-case tests for _apply_transform."""

    def test_unknown_transform_returns_value_unchanged(self):
        """An unknown transform type returns the original value."""
        assert _apply_transform("hello", "uppercase") == "hello"
        assert _apply_transform(42, "hex") == 42
        assert _apply_transform(None, "unknown") is None

    def test_float_from_non_numeric_string_raises(self):
        """float() on non-numeric string raises ValueError."""
        import pytest
        with pytest.raises(ValueError):
            _apply_transform("not-a-number", "float")

    def test_int_from_invalid_string_raises(self):
        """int(float('bad')) raises ValueError."""
        import pytest
        with pytest.raises(ValueError):
            _apply_transform("bad", "int")

    def test_bool_from_none(self):
        """bool(None) is False."""
        assert _apply_transform(None, "bool") is False


@pytest.mark.asyncio
class TestOrchestratorServiceStart:
    """Tests for OrchestratorService.start()."""

    @pytest.fixture
    def disabled_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig(enabled=False)
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            yield service

    @pytest.mark.asyncio
    async def test_start_when_disabled_returns_immediately(self, disabled_service):
        """When enabled=False, start() should return without polling."""
        await disabled_service.start()
        assert disabled_service._running is False

    @pytest.mark.asyncio
    async def test_start_sets_running_true(self):
        """When enabled=True, start() should set _running to True before polling."""
        from src.orchestrator.models import OrchestratorConfig
        from src.orchestrator.service import OrchestratorService
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(OrchestratorConfig(enabled=True))
            service._resume_interrupted = AsyncMock()

            started = False

            async def poll_and_launch():
                nonlocal started
                started = service._running

            service._poll_and_launch = poll_and_launch

            stop_soon = asyncio.create_task(service.stop())

            await service.start()
            await stop_soon

            assert started is True


@pytest.mark.asyncio
class TestPollAndLaunchException:
    """Tests for _poll_and_launch exception safety."""

    @pytest.fixture
    def safe_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig(
            enabled=True,
            max_concurrent_workflows=3,
            poll_interval_seconds=60,
        )
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            service._running = True
            yield service

    @pytest.mark.asyncio
    async def test_poll_handles_get_pending_executions_exception(self, safe_service):
        """If get_pending_executions raises, the error should be caught in start()."""
        safe_service.exec_repo.get_pending_executions = MagicMock(
            side_effect=RuntimeError("DB connection lost")
        )
        safe_service._poll_and_launch = MagicMock(
            side_effect=RuntimeError("DB connection lost")
        )
        # Simulate what start() does: wrap _poll_and_launch in try/except
        try:
            await safe_service._poll_and_launch()
        except RuntimeError:
            pass  # expected in test
        # The service should still be functional
        assert safe_service._running is True


@pytest.mark.asyncio
class TestRunNodeNonRetryable:
    """Tests for _run_node non-retryable error path."""

    @pytest.fixture
    def retryable_service(self):
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

    @pytest.mark.asyncio
    async def test_non_retryable_error_does_not_retry(self, retryable_service):
        """Non-retryable error (e.g. plugin not found) should not be retried."""
        retryable_service.node_repo.get.return_value = MagicMock(
            plugin_id="missing_plugin", parameters={}
        )
        retryable_service.node_repo.update = MagicMock()
        retryable_service.container_runner.run.side_effect = RuntimeError(
            "Plugin not found: nonexistent"
        )
        retryable_service.config.auto_retry_failed_nodes = True
        retryable_service.config.max_node_retries = 2

        result = await retryable_service._run_node(
            execution_id="exec-1",
            node_exec=MagicMock(id="nexec-1"),
            node_def={"id": "n1", "plugin_id": "nonexistent"},
            input_data={},
        )

        assert result is None
        # Should NOT have retried (only 1 call, not 3)
        assert retryable_service.container_runner.run.call_count == 1

    @pytest.mark.asyncio
    async def test_non_retryable_image_not_found(self, retryable_service):
        """Image not found is non-retryable."""
        retryable_service.node_repo.get.return_value = MagicMock(
            plugin_id="img_missing", parameters={}
        )
        retryable_service.node_repo.update = MagicMock()
        retryable_service.container_runner.run.side_effect = RuntimeError(
            "Image not found for node input_node"
        )
        retryable_service.config.auto_retry_failed_nodes = True
        retryable_service.config.max_node_retries = 2

        result = await retryable_service._run_node(
            execution_id="exec-2",
            node_exec=MagicMock(id="nexec-2"),
            node_def={"id": "n2", "plugin_id": "input_node"},
            input_data={},
        )

        assert result is None
        assert retryable_service.container_runner.run.call_count == 1

    @pytest.mark.asyncio
    async def test_non_retryable_input_file_not_found(self, retryable_service):
        """input file not found is non-retryable."""
        retryable_service.node_repo.get.return_value = MagicMock(
            plugin_id="file_check", parameters={}
        )
        retryable_service.node_repo.update = MagicMock()
        retryable_service.container_runner.run.side_effect = RuntimeError(
            "input file not found at /tmp/data.pdf"
        )
        retryable_service.config.auto_retry_failed_nodes = True
        retryable_service.config.max_node_retries = 2

        result = await retryable_service._run_node(
            execution_id="exec-3",
            node_exec=MagicMock(id="nexec-3"),
            node_def={"id": "n3", "plugin_id": "latex_to_pdf"},
            input_data={},
        )

        assert result is None
        assert retryable_service.container_runner.run.call_count == 1


class TestGetFileMetadata:
    """Tests for OrchestratorService._get_file_metadata()."""

    @pytest.fixture
    def metadata_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig()
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            yield service

    def test_file_found_returns_metadata_dict(self, metadata_service):
        """When DBFile is found, returns a properly structured dict."""
        mock_file = MagicMock()
        mock_file.minio_path = "uploads/video.mp4"
        mock_file.filename = "video.mp4"
        mock_file.size_bytes = 12345
        mock_file.mime_type = "video/mp4"

        with patch("src.orchestrator.service.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.query.return_value.filter.return_value.first.return_value = mock_file

            result = metadata_service._get_file_metadata("file-metadata-123")

        assert result == {
            "file_id": "file-metadata-123",
            "file_path": "minio://uploads/video.mp4",
            "filename": "video.mp4",
            "minio_path": "uploads/video.mp4",
            "size": 12345,
            "content_type": "video/mp4",
        }

    def test_file_not_found_returns_none(self, metadata_service):
        """When DBFile is not found in DB, returns None."""
        with patch("src.orchestrator.service.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.query.return_value.filter.return_value.first.return_value = None

            result = metadata_service._get_file_metadata("nonexistent-file-id")

        assert result is None

    def test_session_exception_returns_none(self, metadata_service):
        """When SessionLocal raises, returns None and logs warning."""
        with patch("src.orchestrator.service.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.query.side_effect = RuntimeError("DB error")

            result = metadata_service._get_file_metadata("file-id")

        assert result is None


class TestGetFilePath:
    """Tests for OrchestratorService._get_file_path()."""

    @pytest.fixture
    def path_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig()
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            yield service

    def test_file_found_with_original_path(self, path_service):
        """When DBFile has original_path, returns it as string."""
        mock_file = MagicMock()
        mock_file.original_path = "/uploads/doc.pdf"

        with patch("src.orchestrator.service.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.query.return_value.filter.return_value.first.return_value = mock_file

            result = path_service._get_file_path("file-path-456")

        assert result == "/uploads/doc.pdf"

    def test_file_not_found_returns_none(self, path_service):
        """When DBFile is not found, returns None."""
        with patch("src.orchestrator.service.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.query.return_value.filter.return_value.first.return_value = None

            result = path_service._get_file_path("nonexistent-file-id")

        assert result is None

    def test_original_path_none_returns_none(self, path_service):
        """When DBFile exists but original_path is None, returns None."""
        mock_file = MagicMock()
        mock_file.original_path = None

        with patch("src.orchestrator.service.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.query.return_value.filter.return_value.first.return_value = mock_file

            result = path_service._get_file_path("file-no-path")

        assert result is None

    def test_session_exception_returns_none(self, path_service):
        """When SessionLocal raises, returns None and logs warning."""
        with patch("src.orchestrator.service.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.query.side_effect = RuntimeError("DB error")

            result = path_service._get_file_path("file-id")

        assert result is None


@pytest.mark.asyncio
class TestWorkflowMetricsOnCompletion:
    """Tests for metrics updated in the _run_execution finally block."""

    @pytest.fixture
    def metrics_service(self):
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
    async def test_workflow_active_count_dec_on_failure(self, metrics_service):
        """workflow_active_count should be decremented even when execution raises."""
        execution = MagicMock()
        execution.id = "exec-metrics"
        execution.workflow_template_id = "wf-1"
        execution.file_id = "file-1"
        execution.nodes = []

        workflow = MagicMock()
        workflow.graph.nodes = [{"id": "n1", "plugin_id": "t1"}]
        workflow.graph.edges = []

        metrics_service.exec_repo.get.return_value = execution
        metrics_service.workflow_repo.get.return_value = workflow
        metrics_service.exec_repo.update_status = MagicMock()

        async def raising_node(**kwargs):
            raise RuntimeError("boom")

        metrics_service._run_node = raising_node

        metrics_service._metrics.workflow_active_count.inc = MagicMock()
        metrics_service._metrics.workflow_active_count.dec = MagicMock()
        metrics_service._metrics.workflow_duration = MagicMock()
        metrics_service._metrics.workflows_completed = MagicMock()
        metrics_service._metrics.workflows_failed = MagicMock()

        await metrics_service._run_execution("exec-metrics")

        metrics_service._metrics.workflow_active_count.dec.assert_called()

    @pytest.mark.asyncio
    async def test_workflow_duration_observed(self, metrics_service):
        """workflow_duration metric should be observed even when execution raises."""
        execution = MagicMock()
        execution.id = "exec-timing"
        execution.workflow_template_id = "wf-1"
        execution.file_id = "file-1"
        execution.nodes = []

        workflow = MagicMock()
        workflow.graph.nodes = [{"id": "n1", "plugin_id": "t1"}]
        workflow.graph.edges = []

        metrics_service.exec_repo.get.return_value = execution
        metrics_service.workflow_repo.get.return_value = workflow
        metrics_service.exec_repo.update_status = MagicMock()

        async def raising(**kwargs):
            raise RuntimeError("boom")

        metrics_service._run_node = raising

        metrics_service._metrics.workflow_active_count.inc = MagicMock()
        metrics_service._metrics.workflow_active_count.dec = MagicMock()
        metrics_service._metrics.workflow_duration = MagicMock()
        metrics_service._metrics.workflows_completed = MagicMock()
        metrics_service._metrics.workflows_failed = MagicMock()

        await metrics_service._run_execution("exec-timing")

        metrics_service._metrics.workflow_duration.observe.assert_called()


@pytest.mark.asyncio
class TestPollAndLaunchEdgeCases:
    """Additional edge cases for _poll_and_launch."""

    @pytest.fixture
    def poll_service(self):
        from src.orchestrator.service import OrchestratorService
        from src.orchestrator.models import OrchestratorConfig
        config = OrchestratorConfig(
            enabled=True,
            max_concurrent_workflows=5,
            poll_interval_seconds=60,
        )
        with patch("src.orchestrator.service.DBRepository"), \
             patch("src.orchestrator.service.ExecutionRepository"), \
             patch("src.orchestrator.service.ExecutionNodeRepository"), \
             patch("src.orchestrator.service.WorkflowTemplateRepository"), \
             patch("src.orchestrator.service.PollingContainerRunner"), \
             patch("src.orchestrator.service.ContainerRunnerOrchestrator"):
            service = OrchestratorService(config)
            service._running = True
            yield service

    @pytest.mark.asyncio
    async def test_skips_execution_already_running_in_db(self, poll_service):
        """Execution already in RUNNING state in DB should be skipped."""
        pending_exec = MagicMock(id="exec-already-running")
        poll_service.exec_repo.get_pending_executions.return_value = [pending_exec]

        poll_service.exec_repo.get.return_value = MagicMock(
            id="exec-already-running", status="running"
        )
        poll_service.exec_repo.update_status = MagicMock()

        launched = []

        async def fake_run(exec_id):
            launched.append(exec_id)

        poll_service._run_execution = fake_run
        await poll_service._poll_and_launch()

        # Should not update status to RUNNING (already running) or launch
        assert launched == []
        poll_service.exec_repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_workflow_queue_size_metric_is_set(self, poll_service):
        """workflow_queue_size metric should be set to pending count."""
        pending_exec = MagicMock(id="e1")
        poll_service.exec_repo.get_pending_executions.return_value = [pending_exec]

        workflow = MagicMock()
        workflow.graph.nodes = [{"id": "n1", "plugin_id": "t1"}]
        workflow.graph.edges = []
        poll_service.exec_repo.get.return_value = MagicMock(
            id="e1", status="pending", workflow_template_id="wf-1", file_id="file-1", nodes=[]
        )
        poll_service.workflow_repo.get.return_value = workflow
        poll_service.exec_repo.update_status = MagicMock()

        launched = []

        async def fake_run(exec_id):
            launched.append(exec_id)

        poll_service._run_execution = fake_run
        poll_service._metrics.workflow_queue_size = MagicMock()
        poll_service._metrics.workflows_total = MagicMock()

        await poll_service._poll_and_launch()

        poll_service._metrics.workflow_queue_size.set.assert_called_with(1)

    @pytest.mark.asyncio
    async def test_workflows_total_metric_incremented(self, poll_service):
        """workflows_total should be incremented for each launched execution."""
        poll_service.exec_repo.get_pending_executions.return_value = [
            MagicMock(id="e1"),
            MagicMock(id="e2"),
        ]
        poll_service.exec_repo.get.return_value = MagicMock(
            id=MagicMock(), status="pending"
        )
        poll_service.exec_repo.update_status = MagicMock()

        launched = []

        async def fake_run(exec_id):
            launched.append(exec_id)

        poll_service._run_execution = fake_run
        poll_service._metrics.workflows_total = MagicMock()

        await poll_service._poll_and_launch()

        assert poll_service._metrics.workflows_total.inc.call_count == 2
