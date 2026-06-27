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
            max_concurrent_nodes=self.config.max_concurrent_nodes,
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
            # Guard against: this execution was picked up by _resume_interrupted()
            # in the same event-loop iteration. Tasks are scheduled but haven't run yet
            # (status not changed to RUNNING), so we must also filter by status.
            if execution_id in self._active_executions:
                continue
            # Re-read status to handle the race where _resume_interrupted() already
            # changed this execution to RUNNING (its task is scheduled but not yet executing).
            exec_record = self.exec_repo.get(execution_id)
            if exec_record and exec_record.status != ExecutionStatus.PENDING:
                continue
            # Mark RUNNING immediately — before the task is scheduled — so the next poll
            # iteration (5 seconds later) won't pick up this execution again.
            self.exec_repo.update_status(execution_id, ExecutionStatus.RUNNING)
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
        """Выполнить воркфлоу: топологическая сортировка → параллельное выполнение нод."""
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

            # Подготовить __input для input_mapping
            # Для новых workflow: input_files = {node_id: file_id}
            # Для старых workflow: fallback к file_id
            node_outputs["__input"] = {}
            if hasattr(execution, "input_files") and execution.input_files:
                # Новый формат: множественные входы
                for node_id, file_id in execution.input_files.items():
                    node_outputs["__input"][f"{node_id}.file_id"] = file_id
                    file_metadata = self._get_file_metadata(file_id)
                    if file_metadata:
                        node_outputs["__input"][f"{node_id}.file_path"] = file_metadata["file_path"]
                        node_outputs["__input"][f"{node_id}.filename"] = file_metadata["filename"]
                        node_outputs["__input"][f"{node_id}.minio_path"] = file_metadata["minio_path"]
                        node_outputs["__input"][f"{node_id}.size"] = file_metadata["size"]
                        node_outputs["__input"][f"{node_id}.content_type"] = file_metadata["content_type"]
            elif execution.file_id:
                # Старый формат: один файл на весь workflow
                node_outputs["__input"]["file_id"] = str(execution.file_id)
                file_metadata = self._get_file_metadata(str(execution.file_id))
                if file_metadata:
                    node_outputs["__input"]["file_path"] = file_metadata["file_path"]
                    node_outputs["__input"]["filename"] = file_metadata["filename"]
                    node_outputs["__input"]["minio_path"] = file_metadata["minio_path"]
                    node_outputs["__input"]["size"] = file_metadata["size"]
                    node_outputs["__input"]["content_type"] = file_metadata["content_type"]

            execution_file_id = str(execution.file_id) if execution.file_id else ""
            execution_file_path = self._get_file_path(execution_file_id) if execution_file_id else None

            # Пропускаем уже завершённые ноды, восстанавливаем их outputs
            for node_def in sorted_nodes:
                node_id = node_def["id"]
                node_exec = execution_nodes.get(node_id)
                if node_exec and node_exec.status == NodeExecutionStatus.COMPLETED:
                    logger.info("node_already_completed_skipping", node_id=node_id)
                    completed.add(node_id)
                    node_outputs[node_id] = node_exec.output_data or {}

            # Параллельное выполнение нод с глобальным лимитом
            semaphore = asyncio.Semaphore(self.config.max_concurrent_nodes)
            tasks: Dict[str, asyncio.Task] = {}
            pending_ids = {n["id"] for n in sorted_nodes} - completed
            completed_event = asyncio.Event()
            failed = False

            async def run_node_task(node_def: Dict) -> None:
                nonlocal failed
                node_id = node_def["id"]
                await semaphore.acquire()
                try:
                    # Ждём готовности зависимостей
                    while not all(dep in completed for dep in deps[node_id]):
                        await asyncio.sleep(0.2)
                        try:
                            exec_record = self.exec_repo.get(execution_id)
                            if exec_record and str(exec_record.status) == str(ExecutionStatus.CANCELLED):
                                return
                        except Exception:
                            pass

                    node_exec = execution_nodes.get(node_id)
                    if not node_exec:
                        return

                    input_data = _map_inputs(node_def, deps[node_id], node_outputs, execution_file_id, execution_file_path)
                    node_output = await self._run_node(
                        execution_id=execution_id,
                        node_exec=node_exec,
                        node_def=node_def,
                        input_data=input_data,
                    )

                    async with self._lock:
                        if node_output is not None:
                            completed.add(node_id)
                            node_outputs[node_id] = node_output
                            del tasks[node_id]
                            # Запускаем newly ready ноды
                            for nid in list(pending_ids - completed):
                                if all(dep in completed for dep in deps[nid]) and nid not in tasks:
                                    node_def_ready = next(n for n in sorted_nodes if n["id"] == nid)
                                    tasks[nid] = asyncio.create_task(run_node_task(node_def_ready))
                        else:
                            logger.error("node_failed_stopping_workflow", node_id=node_id)
                            self.exec_repo.update_status(execution_id, ExecutionStatus.FAILED, f"Node {node_id} failed")
                            failed = True
                            for t in tasks.values():
                                t.cancel()
                            tasks.clear()
                            completed_event.set()
                finally:
                    semaphore.release()
                    async with self._lock:
                        if not tasks and not failed:
                            completed_event.set()

            # Запускаем все ноды, готовые сразу (без pending зависимостей)
            async with self._lock:
                for node_def in sorted_nodes:
                    node_id = node_def["id"]
                    if node_id in completed or node_id in tasks:
                        continue
                    if all(dep in completed for dep in deps[node_id]):
                        tasks[node_id] = asyncio.create_task(run_node_task(node_def))

            # Если нечего запускать — сразу завершаем
            if not tasks:
                if not failed:
                    self.exec_repo.update_status(execution_id, ExecutionStatus.COMPLETED)
                    logger.info("execution_completed", execution_id=execution_id)
                return

            # Ждём завершения (с периодической проверкой CANCELLED)
            while True:
                if completed_event.is_set():
                    break
                await asyncio.sleep(1.0)
                exec_record = self.exec_repo.get(execution_id)
                if exec_record and str(exec_record.status) == str(ExecutionStatus.CANCELLED):
                    for t in tasks.values():
                        t.cancel()
                    return

            exec_record = self.exec_repo.get(execution_id)
            if failed or (exec_record and str(exec_record.status) == str(ExecutionStatus.FAILED)):
                return

            pending_not_done = pending_ids - completed
            if pending_not_done:
                self.exec_repo.update_status(execution_id, ExecutionStatus.FAILED, f"Nodes failed: {pending_not_done}")
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
    ) -> Dict[str, Any] | None:
        """
        Выполнить одну ноду с retry-логикой.
        Возвращает output_data при успехе, None при неудаче.
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
                    attempt=attempt + 1,
                ),
            )

            self.node_repo.update(
                node_id=str(node_exec.id),
                status=NodeExecutionStatus.COMPLETED,
                progress_percent=100,
                progress_message="Готово",
                input_data=input_data,
                output_data=output_data,
            )
            elapsed_ms = (time.monotonic() - node_start) * 1000
            self._metrics.node_execution_duration.labels(node_id=node_id).observe(elapsed_ms / 1000)

            # Collect LLM metrics from Pushgateway after node completion
            try:
                from src.utils.pushgateway_collector import replay_llm_metrics
                from src.config import config
                pushgateway_url = getattr(config, 'pushgateway_url', 'localhost:9091')
                replay_llm_metrics(plugin_id, execution_id, pushgateway_url)
            except Exception as metrics_err:
                logger.warning(
                    "failed_to_collect_plugin_metrics",
                    plugin_id=plugin_id,
                    execution_id=execution_id,
                    error=str(metrics_err)
                )

            logger.info("node_completed", execution_id=execution_id, node_id=node_id)
            return output_data if output_data else None

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
            return None

    def _find_node(self, execution, node_id: str):
        """Найти DBExecutionNode по node_id внутри execution."""
        for node in execution.nodes:
            if str(node.node_id) == node_id:
                return node
        return None

    def _get_file_path(self, file_id: str) -> str | None:
        """Получить путь к файлу по file_id для передачи в плагин."""
        try:
            from src.db.entity import DBFile
            from src.db.database import SessionLocal
            session = SessionLocal()
            try:
                db_file = session.query(DBFile).filter(DBFile.id == file_id).first()
                if db_file is None:
                    return None
                original_path = getattr(db_file, "original_path", None)
                if original_path is None:
                    return None
                return str(original_path)
            finally:
                session.close()
        except Exception as e:
            logger.warning("file_lookup_failed", file_id=file_id, error=str(e))
        return None

    def _get_file_metadata(self, file_id: str) -> dict | None:
        """Получить все метаданные файла по file_id для передачи в input плагин."""
        try:
            from src.db.entity import DBFile
            from src.db.database import SessionLocal
            session = SessionLocal()
            try:
                db_file = session.query(DBFile).filter(DBFile.id == file_id).first()
                if db_file is None:
                    return None
                return {
                    "file_id": file_id,
                    "file_path": f"minio://{db_file.minio_path}",
                    "filename": db_file.filename,
                    "minio_path": db_file.minio_path,
                    "size": db_file.size_bytes,
                    "content_type": db_file.mime_type,
                }
            finally:
                session.close()
        except Exception as e:
            logger.warning("file_metadata_lookup_failed", file_id=file_id, error=str(e))
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
    file_path: str | None = None,
) -> Dict[str, Any]:
    """Применить input_mapping: $node_id.output.field или $__input.field → value."""
    input_mapping = node_def.get("input_mapping", [])
    plugin_id = node_def.get("plugin_id", "")

    # Input плагин — source node для динамических файлов.
    # Не добавляем execution.file_id автоматически, file_id должен прийти через input_mapping.
    is_input_plugin = plugin_id == "input"

    if not input_mapping:
        result = {}
        if dependencies:
            result = node_outputs.get(dependencies[0], {}).copy()
        # Для input плагина НЕ добавляем execution.file_id автоматически
        if not is_input_plugin:
            result["file_id"] = file_id
            if file_path:
                result["file_path"] = file_path
        return result

    # Always pass file_id from the workflow execution root file
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

    # Preserve file_id from upstream if it was set via input_mapping.
    # Only fall back to execution-level file_id if the mapping didn't already set one.
    if "file_id" not in result:
        # Check if any dependency already has file_id in its output
        # (e.g. speech_to_text returns file_id for its txt artifact)
        for dep in dependencies:
            dep_output = node_outputs.get(dep, {})
            if dep_output.get("file_id"):
                result["file_id"] = dep_output["file_id"]
                break
        # Last fallback: execution-level file_id (НЕ для input плагина)
        if "file_id" not in result and not is_input_plugin:
            result["file_id"] = file_id
    if file_path and not is_input_plugin:
        result["file_path"] = file_path

    logger.debug(
        "input_mapping_complete",
        node_id=node_def.get("id"),
        input_mapping=input_mapping,
        result_keys=list(result.keys()),
        result_file_id=result.get("file_id"),
        execution_file_id=file_id,
    )
    logger.info(
        "input_data_for_node",
        node_id=node_def.get("id"),
        input_data_keys=list(result.keys()),
        txt_path=result.get("txt_path"),
        media_path=result.get("media_path"),
        latex_path=result.get("latex_path"),
        file_path=result.get("file_path"),
        file_id=result.get("file_id"),
    )
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
