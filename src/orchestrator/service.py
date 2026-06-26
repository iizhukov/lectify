"""
OrchestratorService — главный сервис оркестратора.
Запускается как отдельный asyncio процесс, опрашивает БД и выполняет воркфлоу.
"""
import asyncio
import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any, Dict, List, Set, cast

from src.db.entity import ExecutionStatus, NodeExecutionStatus
from src.db.repository import (
    DBRepository,
    ExecutionRepository,
    ExecutionNodeRepository,
    WorkflowTemplateRepository,
)
from src.docker.runner import PollingContainerRunner
from src.orchestrator.models import OrchestratorConfig
from src.orchestrator.container_runner import ContainerRunnerOrchestrator
from src.utils.logging import get_logger
from src.utils.metrics import get_metrics

if TYPE_CHECKING:
    from src.db.entity import DBExecution

logger = get_logger(__name__)


class OrchestratorService:
    """
    Сервис-оркестратор. Опрос БД, выполнение воркфлоу, перезапуск упавших нод.

    Жизненный цикл:
    1. start() — запускает polling loop
    2. polling loop: читает PENDING воркфлоу из БД, запускает _run_execution()
    3. _run_execution(): топологическая сортировка → последовательное выполнение нод
    4. при ошибке ноды: retry до max_retries, потом FAILED
    """

    def __init__(self, config: OrchestratorConfig | None = None):
        self.config = config or OrchestratorConfig()
        self.db = DBRepository()
        self.exec_repo = ExecutionRepository()
        self.node_repo = ExecutionNodeRepository()
        self.workflow_repo = WorkflowTemplateRepository()
        self.docker_runner = PollingContainerRunner()
        self.container_runner = ContainerRunnerOrchestrator(
            docker_runner=self.docker_runner,
        )
        self._running = False
        self._lock = asyncio.Lock()
        self._active_executions: Set[str] = set()
        self._metrics = get_metrics()

    async def start(self):
        """Главный цикл: запускается при старте приложения и работает до shutdown."""
        if not self.config.enabled:
            logger.info("orchestrator_disabled")
            return

        self._running = True
        logger.info(
            "orchestrator_started",
            poll_interval=self.config.poll_interval_seconds,
            max_concurrent=self.config.max_concurrent_workflows,
        )

        # Восстановление прерванных воркфлоу
        await self._resume_interrupted()

        while self._running:
            try:
                await self._poll_and_launch()
            except Exception as e:
                logger.error("orchestrator_poll_error", error=str(e), exc_info=True)
            await asyncio.sleep(self.config.poll_interval_seconds)

        logger.info("orchestrator_stopped")

    async def stop(self):
        """Остановить оркестратор."""
        self._running = False

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_and_launch(self):
        """Опросить БД и запустить новые/прерванные воркфлоу."""
        pending = self.exec_repo.get_pending_executions()
        self._metrics.workflow_queue_size.set(len(pending))

        if len(self._active_executions) >= self.config.max_concurrent_workflows:
            return

        for execution in pending[: self.config.max_concurrent_workflows - len(self._active_executions)]:
            execution_id = str(execution.id)
            if execution_id not in self._active_executions:
                asyncio.create_task(self._run_execution(execution_id))
                self._active_executions.add(execution_id)
                self._metrics.workflows_total.inc()

    async def _resume_interrupted(self):
        """Восстановить воркфлоу со статусом RUNNING (были прерваны при рестарте)."""
        executions = self.exec_repo.get_running_executions()
        logger.info("resuming_interrupted_executions", count=len(executions))
        for execution in executions:
            execution_id = str(execution.id)
            if execution_id not in self._active_executions:
                asyncio.create_task(self._run_execution(execution_id))
                self._active_executions.add(execution_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _run_execution(self, execution_id: str):
        """Выполнить воркфлоу: топологическая сортировка → ноды по порядку."""
        logger.info("execution_started", execution_id=execution_id)
        self._metrics.workflow_active_count.inc()
        start_time = time.monotonic()

        try:
            execution = self.exec_repo.get(execution_id)
            if not execution:
                logger.error("execution_not_found", execution_id=execution_id)
                return

            workflow = self.workflow_repo.get(str(execution.workflow_template_id))
            if not workflow:
                logger.error("workflow_template_not_found", execution_id=execution_id)
                self.exec_repo.update_status(execution_id, ExecutionStatus.FAILED, "Workflow template not found")
                return

            self.exec_repo.update_status(execution_id, ExecutionStatus.RUNNING)
            graph = workflow.graph
            graph_nodes = [n.model_dump() for n in graph.nodes]
            graph_edges = [e.model_dump() for e in graph.edges]
            sorted_nodes = _topological_sort(graph_nodes, graph_edges)
            deps = _build_dependency_map(graph_nodes, graph_edges)
            completed: Set[str] = set()
            node_outputs: Dict[str, Dict[str, Any]] = {}
            execution_nodes: Dict[str, Any] = {
                cast(str, n["id"]): self._find_node(execution, cast(str, n["id"])) for n in graph_nodes
            }
            execution_file_id = str(execution.file_id)

            for node_def in sorted_nodes:
                node_id = node_def["id"]
                node_exec = execution_nodes.get(node_id)
                if not node_exec:
                    logger.error("node_execution_record_not_found", node_id=node_id)
                    continue

                # Ждём готовности зависимостей
                while not all(dep in completed for dep in deps[node_id]):
                    await asyncio.sleep(0.5)
                    running_exec = self.exec_repo.get(execution_id)
                    if running_exec is not None and str(running_exec.status) == str(ExecutionStatus.CANCELLED):
                        return

                # Маппим входы
                input_data = _map_inputs(node_def, deps[node_id], node_outputs, execution_file_id)

                # Выполняем ноду
                success = await self._run_node(
                    execution_id=execution_id,
                    node_exec=node_exec,
                    node_def=node_def,
                    input_data=input_data,
                )

                if success:
                    completed.add(node_id)
                else:
                    logger.error("node_failed_stopping_workflow", node_id=node_id)
                    self.exec_repo.update_status(execution_id, ExecutionStatus.FAILED, f"Node {node_id} failed")
                    self._active_executions.discard(execution_id)
                    return

            self.exec_repo.update_status(execution_id, ExecutionStatus.COMPLETED)
            logger.info("execution_completed", execution_id=execution_id)

        except Exception as e:
            logger.error("execution_failed", execution_id=execution_id, error=str(e), exc_info=True)
            self.exec_repo.update_status(execution_id, ExecutionStatus.FAILED, str(e))
        finally:
            elapsed = time.monotonic() - start_time
            self._metrics.workflow_duration.observe(elapsed)
            self._metrics.workflow_active_count.dec()
            self._active_executions.discard(execution_id)

            # Record completion vs failure based on final status
            try:
                execution = self.exec_repo.get(execution_id)
                if execution is not None:
                    status = str(execution.status)
                    if status == str(ExecutionStatus.COMPLETED):
                        self._metrics.workflows_completed.inc()
                    elif status == str(ExecutionStatus.FAILED):
                        self._metrics.workflows_failed.inc()
            except Exception:
                pass

    async def _run_node(
        self,
        execution_id: str,
        node_exec,
        node_def: Dict[str, Any],
        input_data: Dict[str, Any],
        attempt: int = 0,
    ) -> bool:
        """
        Выполнить одну ноду с retry-логикой.
        Возвращает True при успехе, False при неудаче.
        """
        node_id = node_def["id"]
        plugin_id = node_def["plugin_id"]
        parameters = node_def.get("parameters", {})

        logger.info(
            "node_starting",
            execution_id=execution_id,
            node_id=node_id,
            plugin_id=plugin_id,
            attempt=attempt + 1,
        )

        self.node_repo.update(
            node_id=str(node_exec.id),
            status=NodeExecutionStatus.RUNNING,
            progress_percent=0,
            progress_message="Подготовка...",
        )

        def progress_callback(percent: int, message: str):
            self.node_repo.update(
                node_id=str(node_exec.id),
                progress_percent=percent,
                progress_message=message,
            )

        try:
            node_start = time.monotonic()
            output_data = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.container_runner.run(
                    node_exec_id=str(node_exec.id),
                    plugin_id=plugin_id or "unknown",
                    input_data=input_data,
                    parameters=parameters,
                    execution_id=execution_id,
                    node_id=node_id,
                    timeout_seconds=self.config.node_timeout_seconds,
                    on_progress=progress_callback,
                ),
            )

            self.node_repo.update(
                node_id=str(node_exec.id),
                status=NodeExecutionStatus.COMPLETED,
                progress_percent=100,
                progress_message="Готово",
                output_data=output_data,
            )
            elapsed_ms = (time.monotonic() - node_start) * 1000
            self._metrics.node_execution_duration.labels(node_id=node_id).observe(elapsed_ms / 1000)
            logger.info("node_completed", execution_id=execution_id, node_id=node_id)
            return True

        except Exception as e:
            error_msg = str(e)
            logger.error(
                "node_failed",
                execution_id=execution_id,
                node_id=node_id,
                error=error_msg,
                attempt=attempt + 1,
                exc_info=True,
            )
            self._metrics.node_failures.labels(node_id=node_id).inc()

            should_retry = (
                self.config.auto_retry_failed_nodes
                and attempt < self.config.max_node_retries
                and not _is_non_retryable_error(error_msg)
            )

            if should_retry:
                logger.info("node_will_retry", node_id=node_id, next_attempt=attempt + 2)
                await asyncio.sleep(2 ** attempt)  # exponential backoff
                return await self._run_node(
                    execution_id=execution_id,
                    node_exec=node_exec,
                    node_def=node_def,
                    input_data=input_data,
                    attempt=attempt + 1,
                )

            self.node_repo.update(
                node_id=str(node_exec.id),
                status=NodeExecutionStatus.FAILED,
                progress_percent=100,
                progress_message=f"Ошибка: {error_msg}",
                error_message=error_msg,
            )
            return False

    def _find_node(self, execution, node_id: str):
        """Найти DBExecutionNode по node_id внутри execution."""
        for node in execution.nodes:
            if str(node.node_id) == node_id:
                return node
        return None


# ---------------------------------------------------------------------------
# Pure helpers (topological sort, input mapping) — no I/O, no state
# ---------------------------------------------------------------------------

def _topological_sort(
    nodes: List[Dict],
    edges: List[Dict]
) -> List[Dict]:
    """Топологическая сортировка нод (Kahn's algorithm)."""
    adj = defaultdict(list)
    in_degree = {n["id"]: 0 for n in nodes}
    for edge in edges:
        adj[edge["from_node_id"]].append(edge["to_node_id"])
        in_degree[edge["to_node_id"]] += 1

    queue = deque([n["id"] for n in nodes if in_degree[n["id"]] == 0])
    node_map = {n["id"]: n for n in nodes}
    sorted_ids = []

    while queue:
        node_id = queue.popleft()
        sorted_ids.append(node_id)
        for neighbor in adj[node_id]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return [node_map[nid] for nid in sorted_ids if nid in node_map]


def _build_dependency_map(
    nodes: List[Dict],
    edges: List[Dict]
) -> Dict[str, List[str]]:
    """Построить карту зависимостей: node_id → [dependency_node_ids]."""
    deps = {n["id"]: [] for n in nodes}
    for edge in edges:
        if edge["to_node_id"] in deps:
            deps[edge["to_node_id"]].append(edge["from_node_id"])
    return deps


def _map_inputs(
    node_def: Dict,
    dependencies: List[str],
    node_outputs: Dict[str, Dict],
    file_id: str,
) -> Dict[str, Any]:
    """Применить input_mapping: $node_id.output.field или $__input.field → value."""
    input_mapping = node_def.get("input_mapping", [])

    if not input_mapping:
        if dependencies:
            return node_outputs.get(dependencies[0], {})
        return {}

    result = {}
    for rule in input_mapping:
        target = rule["target_field"]
        source = str(rule["source"])

        if source.startswith("$"):
            source = source[1:]
            parts = source.split(".", 2)

            if parts[0] == "__input":
                value = node_outputs.get("__input", {}).get(".".join(parts[1:]))
            elif len(parts) >= 2 and parts[1] == "output":
                source_node = parts[0]
                source_field = ".".join(parts[2:])
                value = node_outputs.get(source_node, {}).get(source_field)
            else:
                value = node_outputs.get("__input", {}).get(source)

            transform = rule.get("transform", "passthrough")
            result[target] = _apply_transform(value, transform)
        else:
            result[target] = source

    return result


def _apply_transform(value: Any, transform: str) -> Any:
    """Применить transform к value."""
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
    return value


def _is_non_retryable_error(error_msg: str) -> bool:
    """Ошибки, которые не стоит перезапускать."""
    non_retryable = [
        "plugin not found",
        "image not found",
        "template not found",
        "input file not found",
    ]
    return any(phrase in error_msg.lower() for phrase in non_retryable)
