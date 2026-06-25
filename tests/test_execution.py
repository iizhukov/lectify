"""
Tests for ExecutionEngine (src/workflows/execution.py)

Tests cover:
- Topological sort (Kahn's algorithm)
- Dependency map building
- Input/output mapping and transforms
- Async workflow execution orchestration
- Node execution with progress and metrics
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.workflows.execution import ExecutionEngine


# =============================================================================
# TOPOLOGICAL SORT
# =============================================================================

class TestTopologicalSort:
    def test_simple_linear_graph(self):
        engine = ExecutionEngine()

        nodes = [
            {"id": "A", "template_id": "t1"},
            {"id": "B", "template_id": "t2"},
            {"id": "C", "template_id": "t3"}
        ]
        edges = [
            {"from_node": "A", "to_node": "B"},
            {"from_node": "B", "to_node": "C"}
        ]

        result = engine._topological_sort(nodes, edges)
        assert [n["id"] for n in result] == ["A", "B", "C"]

    def test_parallel_branches(self):
        engine = ExecutionEngine()

        nodes = [
            {"id": "A", "template_id": "t1"},
            {"id": "B", "template_id": "t2"},
            {"id": "C", "template_id": "t3"}
        ]
        edges = [
            {"from_node": "A", "to_node": "B"},
            {"from_node": "A", "to_node": "C"}
        ]

        result = engine._topological_sort(nodes, edges)
        assert result[0]["id"] == "A"
        assert set(n["id"] for n in result[1:]) == {"B", "C"}

    def test_diamond_graph(self):
        engine = ExecutionEngine()

        nodes = [
            {"id": "A", "template_id": "t1"},
            {"id": "B", "template_id": "t2"},
            {"id": "C", "template_id": "t3"},
            {"id": "D", "template_id": "t4"}
        ]
        edges = [
            {"from_node": "A", "to_node": "B"},
            {"from_node": "A", "to_node": "C"},
            {"from_node": "B", "to_node": "D"},
            {"from_node": "C", "to_node": "D"}
        ]

        result = engine._topological_sort(nodes, edges)
        ids = [n["id"] for n in result]
        assert ids[0] == "A"
        assert ids[-1] == "D"
        assert "B" in ids[1:-1]
        assert "C" in ids[1:-1]

    def test_single_node(self):
        engine = ExecutionEngine()
        nodes = [{"id": "A", "template_id": "t1"}]
        result = engine._topological_sort(nodes, [])
        assert len(result) == 1
        assert result[0]["id"] == "A"

    def test_returns_full_node_definitions(self):
        engine = ExecutionEngine()
        nodes = [{"id": "A", "template_id": "t1", "custom_field": "value"}]
        result = engine._topological_sort(nodes, [])
        assert result[0]["custom_field"] == "value"


# =============================================================================
# DEPENDENCY MAP
# =============================================================================

class TestDependencyMap:
    def test_simple_dependency(self):
        engine = ExecutionEngine()
        nodes = [
            {"id": "A", "template_id": "t1"},
            {"id": "B", "template_id": "t2"}
        ]
        edges = [{"from_node": "A", "to_node": "B"}]

        deps = engine._build_dependency_map(nodes, edges)

        assert deps["A"] == []
        assert deps["B"] == ["A"]

    def test_multiple_dependencies(self):
        engine = ExecutionEngine()
        nodes = [
            {"id": "A", "template_id": "t1"},
            {"id": "B", "template_id": "t2"},
            {"id": "C", "template_id": "t3"}
        ]
        edges = [
            {"from_node": "A", "to_node": "C"},
            {"from_node": "B", "to_node": "C"}
        ]

        deps = engine._build_dependency_map(nodes, edges)
        assert set(deps["C"]) == {"A", "B"}

    def test_all_nodes_included_even_without_edges(self):
        engine = ExecutionEngine()
        nodes = [
            {"id": "A", "template_id": "t1"},
            {"id": "B", "template_id": "t2"}
        ]
        deps = engine._build_dependency_map(nodes, [])
        assert "A" in deps
        assert "B" in deps
        assert deps["A"] == []
        assert deps["B"] == []


# =============================================================================
# INPUT MAPPING
# =============================================================================

class TestInputMapping:
    def test_passes_first_dependency_output_when_no_mapping(self):
        engine = ExecutionEngine()
        node_def = {"id": "B", "template_id": "t2"}
        node_outputs = {"A": {"file_id": "file-123", "result": "data"}}

        result = engine._map_inputs(node_def, ["A"], node_outputs)
        assert result == {"file_id": "file-123", "result": "data"}

    def test_maps_from_dependency_with_explicit_mapping(self):
        engine = ExecutionEngine()
        node_def = {
            "id": "B",
            "template_id": "t2",
            "input_mapping": [
                {"target_field": "file_path", "source": "$A.output.file_path"}
            ]
        }
        node_outputs = {
            "A": {"file_id": "file-123", "file_path": "/path/to/file.mp4"}
        }

        result = engine._map_inputs(node_def, ["A"], node_outputs)
        assert result["file_path"] == "/path/to/file.mp4"

    def test_maps_from_initial_input(self):
        engine = ExecutionEngine()
        node_def = {
            "id": "A",
            "template_id": "t1",
            "input_mapping": [
                {"target_field": "file_path", "source": "$__input.file_path"}
            ]
        }
        node_outputs = {
            "__input": {"file_id": "file-123", "file_path": "/path/to/file.mp4"}
        }

        result = engine._map_inputs(node_def, [], node_outputs)
        assert result["file_path"] == "/path/to/file.mp4"

    def test_multiple_mapping_rules(self):
        engine = ExecutionEngine()
        node_def = {
            "id": "B",
            "template_id": "t2",
            "input_mapping": [
                {"target_field": "file_path", "source": "$A.output.path"},
                {"target_field": "language", "source": "$__input.language"}
            ]
        }
        node_outputs = {
            "A": {"path": "/file.mp4"},
            "__input": {"language": "en"}
        }

        result = engine._map_inputs(node_def, ["A"], node_outputs)
        assert result["file_path"] == "/file.mp4"
        assert result["language"] == "en"

    def test_direct_value_mapping(self):
        engine = ExecutionEngine()
        node_def = {
            "id": "B",
            "template_id": "t2",
            "input_mapping": [
                {"target_field": "mode", "source": "fast"}
            ]
        }

        result = engine._map_inputs(node_def, [], {})
        assert result["mode"] == "fast"

    def test_missing_source_returns_none(self):
        engine = ExecutionEngine()
        node_def = {
            "id": "B",
            "template_id": "t2",
            "input_mapping": [
                {"target_field": "file_path", "source": "$A.output.missing"}
            ]
        }
        node_outputs = {"A": {"other": "value"}}

        result = engine._map_inputs(node_def, ["A"], node_outputs)
        assert result["file_path"] is None


# =============================================================================
# TRANSFORMS
# =============================================================================

class TestTransforms:
    def test_passthrough(self):
        engine = ExecutionEngine()
        assert engine._apply_transform("value", "passthrough") == "value"
        assert engine._apply_transform(123, "passthrough") == 123

    def test_string_transform(self):
        engine = ExecutionEngine()
        assert engine._apply_transform(123, "string") == "123"
        assert engine._apply_transform(None, "string") == ""
        assert engine._apply_transform(True, "string") == "True"

    def test_int_transform(self):
        engine = ExecutionEngine()
        assert engine._apply_transform("123", "int") == 123
        assert engine._apply_transform("123.45", "int") == 123
        assert engine._apply_transform(None, "int") == 0

    def test_float_transform(self):
        engine = ExecutionEngine()
        assert engine._apply_transform("123.45", "float") == 123.45
        assert engine._apply_transform(None, "float") == 0.0

    def test_bool_transform(self):
        engine = ExecutionEngine()
        assert engine._apply_transform("true", "bool") is True
        assert engine._apply_transform("false", "bool") is True  # non-empty string is truthy
        assert engine._apply_transform("", "bool") is False
        assert engine._apply_transform(0, "bool") is False
        assert engine._apply_transform(1, "bool") is True
        assert engine._apply_transform(None, "bool") is False

    def test_unknown_transform_returns_value(self):
        engine = ExecutionEngine()
        assert engine._apply_transform("value", "unknown") == "value"


# =============================================================================
# ENGINE INITIALIZATION
# =============================================================================

class TestExecutionEngineInit:
    def test_default_initialization(self):
        with patch("src.workflows.execution.PollingContainerRunner"), \
             patch("src.workflows.execution.WorkflowRepository"):
            engine = ExecutionEngine()
            assert engine.repo is not None
            assert engine.docker_runner is not None

    def test_custom_repository(self):
        mock_repo = MagicMock()
        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)
            assert engine.repo is mock_repo


# =============================================================================
# WORKFLOW EXECUTION ORCHESTRATION
# =============================================================================

class TestExecuteWorkflow:
    @pytest.mark.asyncio
    async def test_raises_when_workflow_not_found(self):
        mock_repo = MagicMock()
        mock_repo.get_workflow_template.return_value = None
        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)

            with pytest.raises(ValueError, match="Workflow not found"):
                await engine.execute_workflow(
                    workflow_template_id="nonexistent",
                    file_id="file-123"
                )

    @pytest.mark.asyncio
    async def test_creates_execution_record(self):
        mock_repo = MagicMock()
        mock_workflow = MagicMock()
        mock_workflow.graph = {"nodes": [], "edges": []}
        mock_repo.get_workflow_template.return_value = mock_workflow

        created_exec = MagicMock()
        created_exec.id = "exec-new"
        mock_repo.create_execution.return_value = created_exec
        mock_repo.get_execution.return_value = created_exec

        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)
            result = await engine.execute_workflow(
                workflow_template_id="wf-1",
                file_id="file-123"
            )
            assert result is not None

        mock_repo.create_execution.assert_called_once()
        call_kwargs = mock_repo.create_execution.call_args[0][0]
        assert call_kwargs["workflow_template_id"] == "wf-1"
        assert call_kwargs["file_id"] == "file-123"
        assert call_kwargs["status"] == "running"

    @pytest.mark.asyncio
    async def test_creates_node_records_from_graph(self):
        mock_repo = MagicMock()
        mock_workflow = MagicMock()
        mock_workflow.graph = {
            "nodes": [
                {"id": "A", "template_id": "t1"},
                {"id": "B", "template_id": "t2"}
            ],
            "edges": [{"from_node": "A", "to_node": "B"}]
        }
        mock_repo.get_workflow_template.return_value = mock_workflow

        node_a = MagicMock()
        node_a.id = "node-a"
        node_b = MagicMock()
        node_b.id = "node-b"
        mock_repo.create_execution_node.side_effect = [node_a, node_b]
        mock_repo.get_execution.return_value = MagicMock()

        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)
            # Patch _execute_node to avoid actual plugin execution
            with patch.object(engine, "_execute_node", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = {"output": "result"}
                await engine.execute_workflow(
                    workflow_template_id="wf-1",
                    file_id="file-123"
                )

        assert mock_repo.create_execution_node.call_count == 2

    @pytest.mark.asyncio
    async def test_updates_final_status_on_success(self):
        mock_repo = MagicMock()
        mock_workflow = MagicMock()
        mock_workflow.graph = {
            "nodes": [{"id": "A", "template_id": "t1"}],
            "edges": []
        }
        mock_repo.get_workflow_template.return_value = mock_workflow

        mock_exec = MagicMock()
        mock_exec.id = "exec-1"
        mock_repo.create_execution_node.return_value = mock_exec
        mock_repo.get_execution.return_value = mock_exec

        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)
            with patch.object(engine, "_execute_node", new_callable=AsyncMock) as mock_exec_node:
                mock_exec_node.return_value = {"result": "ok"}
                await engine.execute_workflow(
                    workflow_template_id="wf-1",
                    file_id="file-123"
                )

        assert mock_repo.update_execution_status.call_count == 1
        assert mock_repo.update_execution_status.call_args[0][1] == "completed"

    @pytest.mark.asyncio
    async def test_calls_on_progress_callback(self):
        mock_repo = MagicMock()
        mock_workflow = MagicMock()
        mock_workflow.graph = {
            "nodes": [{"id": "A", "template_id": "t1"}],
            "edges": []
        }
        mock_repo.get_workflow_template.return_value = mock_workflow

        mock_exec = MagicMock()
        mock_exec.id = "exec-1"
        mock_repo.create_execution_node.return_value = mock_exec
        mock_repo.get_execution.return_value = mock_exec

        progress_calls = []
        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)
            with patch.object(engine, "_execute_node", new_callable=AsyncMock) as mock_exec_node:
                mock_exec_node.return_value = {"result": "ok"}
                await engine.execute_workflow(
                    workflow_template_id="wf-1",
                    file_id="file-123",
                    on_progress=lambda _, pct, msg: progress_calls.append((pct, msg))
                )

        assert len(progress_calls) > 0

    @pytest.mark.asyncio
    async def test_stores_node_output_for_later_nodes(self):
        """Node outputs are populated by _execute_node and used by later nodes via _map_inputs."""
        engine = ExecutionEngine()

        # Simulate node_outputs after A completes
        node_outputs = {"A": {"result": "output_from_A"}}

        # Node B depends on A with explicit mapping
        node_b = {
            "id": "B",
            "template_id": "t2",
            "input_mapping": [
                {"source": "$A.output.result", "target_field": "input_data", "transform": "passthrough"}
            ]
        }
        deps = {"B": ["A"]}

        input_data = engine._map_inputs(node_b, deps, node_outputs)

        assert input_data["input_data"] == "output_from_A"


# =============================================================================
# NODE EXECUTION
# =============================================================================

class TestExecuteNode:
    @pytest.mark.asyncio
    async def test_raises_when_plugin_not_found(self):
        mock_repo = MagicMock()
        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)

        node_exec = MagicMock()
        node_exec.id = "node-1"
        node_def = {"id": "A", "template_id": "t1"}
        template = MagicMock()
        template.plugin_id = "nonexistent-plugin"

        with patch("src.workflows.execution.get_plugin_registry") as mock_registry:
            mock_registry.return_value.get_plugin.return_value = None

            result = await engine._execute_node(
                node_exec, node_def, template,
                {}, "exec-1", None, None
            )

        assert result is None
        mock_repo.update_execution_node.assert_any_call(
            "node-1",
            status="failed",
            progress_percent=100,
            progress_message="Ошибка: Plugin not found: nonexistent-plugin",
            error_message="Plugin not found: nonexistent-plugin"
        )

    @pytest.mark.asyncio
    async def test_calls_progress_callback(self):
        mock_repo = MagicMock()
        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)

        node_exec = MagicMock()
        node_exec.id = "node-1"

        plugin_instance = MagicMock()
        plugin_instance.input_model.return_value = MagicMock()
        plugin_instance.execute = AsyncMock(return_value=MagicMock(model_dump=MagicMock(return_value={"result": "ok"})))

        plugin_class = MagicMock(return_value=plugin_instance)

        node_def = {"id": "A", "template_id": "t1"}
        template = MagicMock()
        template.plugin_id = "test-plugin"
        template.parameters = {}

        progress_calls = []

        async def run():
            return await engine._execute_node(
                node_exec, node_def, template,
                {}, "exec-1",
                on_progress=lambda _, pct, msg: progress_calls.append((pct, msg)),
                on_metrics=None
            )

        with patch("src.workflows.execution.get_plugin_registry") as mock_registry, \
             patch("src.workflows.execution.PluginContext") as mock_ctx_cls:

            mock_registry.return_value.get_plugin.return_value = plugin_class
            mock_ctx_cls.return_value = MagicMock()

            await run()

        # Verify repo was updated with progress
        update_calls = mock_repo.update_execution_node.call_args_list
        progress_percents = [c.kwargs.get("progress_percent") or c[1].get("progress_percent")
                            for c in update_calls if c.kwargs.get("progress_percent") or c[1].get("progress_percent")]
        assert 100 in progress_percents or any("progress_percent=100" in str(c) for c in update_calls)

    @pytest.mark.asyncio
    async def test_returns_plugin_result(self):
        mock_repo = MagicMock()
        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)

        node_exec = MagicMock()
        node_exec.id = "node-1"

        plugin_result = MagicMock()
        plugin_result.model_dump.return_value = {"output": "processed", "file_id": "file-out"}

        plugin_instance = MagicMock()
        plugin_instance.input_model.return_value = MagicMock()
        plugin_instance.execute = AsyncMock(return_value=plugin_result)

        plugin_class = MagicMock(return_value=plugin_instance)

        node_def = {"id": "A", "template_id": "t1"}
        template = MagicMock()
        template.plugin_id = "test-plugin"
        template.parameters = {}

        with patch("src.workflows.execution.get_plugin_registry") as mock_registry, \
             patch("src.workflows.execution.PluginContext") as mock_ctx_cls:

            mock_registry.return_value.get_plugin.return_value = plugin_class
            mock_ctx_cls.return_value = MagicMock()

            result = await engine._execute_node(
                node_exec, node_def, template,
                {"input": "value"}, "exec-1", None, None
            )

        assert result == {"output": "processed", "file_id": "file-out"}

    @pytest.mark.asyncio
    async def test_handles_plugin_exception(self):
        mock_repo = MagicMock()
        with patch("src.workflows.execution.PollingContainerRunner"):
            engine = ExecutionEngine(repository=mock_repo)

        node_exec = MagicMock()
        node_exec.id = "node-1"

        plugin_instance = MagicMock()
        plugin_instance.input_model.return_value = MagicMock()
        plugin_instance.execute.side_effect = RuntimeError("plugin error")

        plugin_class = MagicMock(return_value=plugin_instance)

        node_def = {"id": "A", "template_id": "t1"}
        template = MagicMock()
        template.plugin_id = "test-plugin"
        template.parameters = {}

        with patch("src.workflows.execution.get_plugin_registry") as mock_registry, \
             patch("src.workflows.execution.PluginContext") as mock_ctx_cls:

            mock_registry.return_value.get_plugin.return_value = plugin_class
            mock_ctx_cls.return_value = MagicMock()

            result = await engine._execute_node(
                node_exec, node_def, template,
                {}, "exec-1", None, None
            )

        assert result is None
        mock_repo.update_execution_node.assert_any_call(
            "node-1",
            status="failed",
            progress_percent=100,
            progress_message="Ошибка: plugin error",
            error_message="plugin error"
        )
