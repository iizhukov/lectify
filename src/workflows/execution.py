"""
Execution Engine — runs workflows with topological sort and parallel execution
"""

import asyncio
import logging
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from src.db.entity import DBExecution, DBExecutionNode
from src.db.repository import WorkflowRepository
from src.db.models import ExecutionModel, ExecutionNodeModel, NodeExecutionStatus
from src.plugins.base import PluginContext
from src.plugins.registry import get_plugin_registry
from src.docker.runner import PollingContainerRunner, ContainerMetrics

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Executes workflow with:
    - Topological sort for dependency ordering
    - Parallel execution of independent nodes
    - Input mapping between nodes
    - Progress tracking
    - Metrics collection
    """

    def __init__(self, repository: WorkflowRepository = None):
        self.repo = repository or WorkflowRepository()
        self.docker_runner = PollingContainerRunner()

    async def execute_workflow(
        self,
        workflow_template_id: str,
        file_id: str,
        user_id: str = None,
        initial_input: Dict[str, Any] = None,
        on_progress: Callable[[str, int, str], None] = None,
        on_node_progress: Callable[[str, int, str], None] = None,
        on_metrics: Callable[[str, ContainerMetrics], None] = None
    ) -> ExecutionModel:
        """
        Execute a workflow.

        Args:
            workflow_template_id: ID of workflow template
            file_id: ID of input file
            user_id: User executing the workflow
            initial_input: Initial input data (e.g., file_path)
            on_progress: Callback for overall progress (execution_id, percent, message)
            on_node_progress: Callback for node progress (node_id, percent, message)
            on_metrics: Callback for node metrics (node_id, metrics)

        Returns:
            ExecutionModel with results
        """
        # 1. Get workflow template
        workflow = self.repo.get_workflow_template(workflow_template_id)
        if not workflow:
            raise ValueError(f"Workflow not found: {workflow_template_id}")

        # 2. Create execution record
        execution_id = str(uuid.uuid4())
        execution = self.repo.create_execution({
            "id": execution_id,
            "workflow_template_id": workflow_template_id,
            "file_id": file_id,
            "user_id": user_id,
            "status": "running",
            "created_at": datetime.now(timezone.utc)
        })

        logger.info(f"Starting execution {execution_id} for workflow {workflow_template_id}")

        try:
            # 3. Topological sort
            graph = workflow.graph
            sorted_nodes = self._topological_sort(graph["nodes"], graph["edges"])

            logger.info(f"Execution order: {[n['id'] for n in sorted_nodes]}")

            # 4. Create execution nodes
            execution_nodes = {}
            for node_def in graph["nodes"]:
                node_exec = self.repo.create_execution_node({
                    "id": str(uuid.uuid4()),
                    "execution_id": execution_id,
                    "node_template_id": node_def["template_id"],
                    "node_id": node_def["id"],
                    "status": "pending",
                    "created_at": datetime.now(timezone.utc)
                })
                execution_nodes[node_def["id"]] = node_exec

            # 5. Build dependency graph
            deps = self._build_dependency_map(graph["nodes"], graph["edges"])

            # 6. Track node outputs for input mapping
            node_outputs: Dict[str, Dict[str, Any]] = {}

            # 7. Initial input
            if initial_input:
                node_outputs["__input"] = initial_input

            # 8. Execute nodes
            completed: Set[str] = set()
            running_tasks: Dict[str, asyncio.Task] = {}
            pending = deque(sorted_nodes)

            total_nodes = len(sorted_nodes)
            completed_count = 0

            while pending or running_tasks:
                # Check for ready nodes
                while pending:
                    node_def = pending[0]
                    node_id = node_def["id"]

                    # Check if all dependencies are satisfied
                    if not all(dep in completed for dep in deps[node_id]):
                        break

                    pending.popleft()

                    # Get node template
                    template = self.repo.get_node_template(node_def["template_id"])
                    if not template:
                        logger.error(f"Template not found: {node_def['template_id']}")
                        continue

                    # Map inputs from dependencies
                    input_data = self._map_inputs(
                        node_def,
                        deps[node_id],
                        node_outputs
                    )

                    # Start async execution
                    task = asyncio.create_task(
                        self._execute_node(
                            node_exec=execution_nodes[node_id],
                            node_def=node_def,
                            template=template,
                            input_data=input_data,
                            execution_id=execution_id,
                            on_progress=lambda n_id, pct, msg: (
                                on_node_progress(n_id, pct, msg) if on_node_progress else None
                            ),
                            on_metrics=lambda n_id, metrics: (
                                on_metrics(n_id, metrics) if on_metrics else None
                            )
                        )
                    )
                    running_tasks[node_id] = task

                # Wait for any task to complete
                if running_tasks:
                    done, pending_tasks = await asyncio.wait(
                        running_tasks.values(),
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    for task in done:
                        # Find which node completed
                        for node_id, t in list(running_tasks.items()):
                            if t in done:
                                try:
                                    result = await task
                                    node_outputs[node_id] = result
                                    completed.add(node_id)
                                    completed_count += 1

                                    # Update overall progress
                                    overall_pct = int(100 * completed_count / total_nodes)
                                    on_progress(
                                        execution_id,
                                        overall_pct,
                                        f"Выполнено {completed_count}/{total_nodes}"
                                    ) if on_progress else None

                                except Exception as e:
                                    logger.error(f"Node {node_id} failed: {e}")
                                    # Mark as failed - could add retry logic here

                                del running_tasks[node_id]
                                break

                # Small delay to avoid busy loop
                await asyncio.sleep(0.1)

            # 9. Finalize execution
            all_failed = len([n for n in node_outputs.values() if n.get("__error")]) > 0
            final_status = "failed" if all_failed else "completed"

            self.repo.update_execution_status(execution_id, final_status)

            logger.info(f"Execution {execution_id} finished with status: {final_status}")

            # Return execution details
            return self.repo.get_execution(execution_id)

        except Exception as e:
            logger.error(f"Execution {execution_id} failed: {e}")
            self.repo.update_execution_status(
                execution_id,
                "failed",
                error_message=str(e)
            )
            raise

    def _topological_sort(
        self,
        nodes: List[Dict],
        edges: List[Dict]
    ) -> List[Dict]:
        """Sort nodes in topological order (Kahn's algorithm)"""
        # Build adjacency and in-degree
        adj = defaultdict(list)
        in_degree = {n["id"]: 0 for n in nodes}

        for edge in edges:
            adj[edge["from_node"]].append(edge["to_node"])
            in_degree[edge["to_node"]] += 1

        # Start with nodes that have no dependencies
        queue = deque([n["id"] for n in nodes if in_degree[n["id"]] == 0])
        sorted_ids = []

        while queue:
            node_id = queue.popleft()
            sorted_ids.append(node_id)

            for neighbor in adj[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Return node definitions in sorted order
        node_map = {n["id"]: n for n in nodes}
        return [node_map[nid] for nid in sorted_ids if nid in node_map]

    def _build_dependency_map(
        self,
        nodes: List[Dict],
        edges: List[Dict]
    ) -> Dict[str, List[str]]:
        """Build map of node_id -> list of dependencies"""
        # Инициализируем все узлы с пустым списком
        deps = {n["id"]: [] for n in nodes}
        for edge in edges:
            to_node = edge["to_node"]
            if to_node in deps:
                deps[to_node].append(edge["from_node"])
        return deps

    def _map_inputs(
        self,
        node_def: Dict,
        dependencies: List[str],
        node_outputs: Dict[str, Dict]
    ) -> Dict[str, Any]:
        """Map inputs from parent node outputs"""
        # Get input mapping from node_def or template
        input_mapping = node_def.get("input_mapping", [])

        if not input_mapping:
            # Default: pass first dependency's output
            if dependencies:
                first_dep = dependencies[0]
                return node_outputs.get(first_dep, {})
            return {}

        # Apply mapping rules
        result = {}
        for rule in input_mapping:
            target = rule["target_field"]
            source = rule["source"]

            # Parse source: "$node_id.output.field_name" или "$__input.field_name"
            if source.startswith("$"):
                # Убираем первый $ и разбиваем
                source = source[1:]  # Убираем $
                parts = source.split(".")

                if parts[0] == "__input":
                    # Формат: $__input.field_name
                    source_field = ".".join(parts[1:])
                    value = node_outputs.get("__input", {}).get(source_field)
                elif len(parts) >= 3 and parts[1] == "output":
                    # Формат: $node_id.output.field_name
                    source_node = parts[0]
                    source_field = ".".join(parts[2:])
                    value = node_outputs.get(source_node, {}).get(source_field)
                else:
                    # Просто имя поля без node_id.output - используем __input
                    value = node_outputs.get("__input", {}).get(source)

                # Apply transform
                transform = rule.get("transform", "passthrough")
                result[target] = self._apply_transform(value, transform)
            else:
                # Direct value
                result[target] = source

        return result

    def _apply_transform(self, value: Any, transform: str) -> Any:
        """Apply transform to value"""
        if transform == "passthrough":
            return value
        elif transform == "string":
            return str(value) if value is not None else ""
        elif transform == "int":
            return int(float(str(value))) if value is not None else 0
        elif transform == "float":
            return float(value) if value is not None else 0.0
        elif transform == "bool":
            return bool(value)
        else:
            return value

    async def _execute_node(
        self,
        node_exec: DBExecutionNode,
        node_def: Dict,
        template,
        input_data: Dict[str, Any],
        execution_id: str,
        on_progress: Optional[Callable] = None,
        on_metrics: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Execute a single node"""
        node_id = node_def["id"]
        plugin_id = template.plugin_id

        # Update status to running
        self.repo.update_execution_node(
            node_exec.id,
            status="running",
            progress_percent=0,
            progress_message="Подготовка..."
        )

        try:
            # Get plugin
            registry = get_plugin_registry()
            plugin_class = registry.get_plugin(plugin_id)

            if not plugin_class:
                raise ValueError(f"Plugin not found: {plugin_id}")

            plugin = plugin_class()

            # Create context
            context = PluginContext(
                execution_id=execution_id,
                node_id=node_id
            )

            # Progress callback
            def progress_callback(percent: int, message: str):
                self.repo.update_execution_node(
                    node_exec.id,
                    progress_percent=percent,
                    progress_message=message
                )
                on_progress(node_id, percent, message)

            context.set_progress_callback(progress_callback)

            # Execute plugin
            input_model = plugin.input_model(**input_data)
            parameters = template.parameters or {}

            result = await plugin.execute(input_model, context, parameters)

            # Update with results
            self.repo.update_execution_node(
                node_exec.id,
                status="completed",
                progress_percent=100,
                progress_message="Готово",
                output_data=result.model_dump()
            )

            return result.model_dump()

        except Exception as e:
            logger.error(f"Node {node_id} execution failed: {e}")
            self.repo.update_execution_node(
                node_exec.id,
                status="failed",
                progress_percent=100,
                progress_message=f"Ошибка: {str(e)}",
                error_message=str(e)
            )
            return None