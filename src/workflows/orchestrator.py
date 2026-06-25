import os
import time
import threading
from queue import Queue, Empty
from typing import Dict, Tuple

from src.db.repository import Repository
from src.db.models import NodeStatus
from src.workflows.registry import WORKFLOW_REGISTRY
from src.workflows.converter import get_converter
from src.nodes.media_converter.models import MediaConverterInput
from src.utils.logging import get_logger
from src.utils.metrics import get_metrics

logger = get_logger(__name__)
metrics = get_metrics()


class LectureOrchestrator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)

            return cls._instance

    def __init__(self, deepseek_client=None):
        if hasattr(self, "_initialized") and self._initialized:
            return
        
        if deepseek_client is None:
            raise ValueError("deepseek_client must be provided on first initialization")

        self.client = deepseek_client
        self._repository = Repository()
        self.workflow = WORKFLOW_REGISTRY["lecture_workflow"]
        self.active_workflows = set()
        self._results_lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._workflow_queue: Queue[Tuple[str, str, str, str]] = Queue()
        self.max_concurrent_workflows = 3
        self._queue_processor_thread = None
        self._initialized = True
        self._start_queue_processor()

    def init_workflow(self, file_id: str):
        self._repository.create_workflow(
            workflow_id=file_id,
            file_id=file_id,
            name=self.workflow.name
        )

        nodes_data = []

        for node in self.workflow.all_nodes:

            dependencies = []

            for parent in self.workflow.all_nodes:
                for child in parent.children:
                    if child.node_id == node.node_id:
                        dependencies.append(parent.node_id)

            nodes_data.append({
                "node_id": node.node_id,
                "node_name": node.name,
                "dependencies": dependencies
            })

        self._repository.create_workflow_nodes(
            workflow_id=file_id,
            file_id=file_id,
            nodes=nodes_data
        )

        return file_id

    def start_orchestration(
        self,
        workflow_id: str,
        file_id: str,
        file_path: str,
        language: str
    ):
        details = self._repository.get_workflow_details(file_id)

        if details and details.graph:
            for node in details.graph.nodes:
                if node.status == NodeStatus.RUNNING:

                    self._repository.update_node(
                        workflow_id=file_id,
                        node_id=node.node_id,
                        status=NodeStatus.PENDING,
                        message="Recovered after restart"
                    )

        if workflow_id in self.active_workflows:
            return

        # Добавляем в очередь вместо немедленного запуска
        self._workflow_queue.put((workflow_id, file_id, file_path, language))
        queue_size = self._workflow_queue.qsize()
        
        logger.info(
            "workflow_queued",
            workflow_id=workflow_id,
            file_id=file_id,
            queue_size=queue_size
        )
        
        metrics.workflows_total.inc()
        metrics.workflow_queue_size.set(queue_size)

    def _run_orchestrator(
        self,
        workflow_id: str,
        file_id: str,
        file_path: str,
        language: str
    ):
        results = {
            "root_input": MediaConverterInput(file_id=file_id, file_path=file_path)
        }
        running_threads = {}
        
        self._repository.update_workflow_status(
            workflow_id,
            NodeStatus.RUNNING
        )
        
        while True:
            workflow_details = self._repository.get_workflow_details(workflow_id)
            if not workflow_details or not workflow_details.graph:
                break
                
            node_states = {node.node_id: node.status for node in workflow_details.graph.nodes}
            
            all_done = True
            for nid, status in node_states.items():
                if status not in ["completed", "failed"]:
                    all_done = False
                    break

            if all_done:
                overall_status = NodeStatus.COMPLETED
                if any(s == "failed" for s in node_states.values()):
                    overall_status = NodeStatus.FAILED
                
                self._repository.update_workflow_status(
                    workflow_id,
                    overall_status
                )
                break

            self._traverse_and_trigger(
                self.workflow.root_node, 
                file_id, 
                language, 
                node_states, 
                running_threads, 
                results,
                parent_node=None
            )
            time.sleep(1)

        with self._queue_lock:
            self.active_workflows.discard(workflow_id)
            active_count = len(self.active_workflows)
        
        logger.info(
            "workflow_completed",
            workflow_id=workflow_id,
            file_id=file_id,
            active_count=active_count
        )
        
        metrics.workflows_completed.inc()
        metrics.workflow_active_count.set(active_count)

    def _traverse_and_trigger(self, node, file_id, language, node_states, running_threads, results, parent_node=None):
        current_status = node_states.get(node.node_id)
        
        if current_status == "completed" and node.node_id not in results:
            file_details = self._repository.get_file_details(file_id)
            db_node = next((n for n in file_details.nodes if n.node_id == node.node_id), None)

            if db_node and db_node.artifact_path:
                fields = node.output_model.model_fields
                path_field_name = None
                for field_name, field_info in fields.items():
                    if field_name != "file_id" and "path" in field_name.lower():
                        path_field_name = field_name
                        break
                
                if path_field_name:
                    kwargs = {"file_id": file_id, path_field_name: db_node.artifact_path}
                    with self._results_lock:
                        results[node.node_id] = node.output_model(**kwargs)

        if (
            current_status in ["pending", "failed"]
            and node.node_id not in running_threads
        ):
            parent_id = parent_node.node_id if parent_node else "root_input"
            
            if parent_id in results:
                parent_output = results[parent_id]
                
                converter = get_converter(type(parent_output), node.input_model)
                if converter:
                    try:
                        node_input = converter(parent_output)
                        
                        t = threading.Thread(
                            target=self._execute_node_thread,
                            args=(node, file_id, language, node_input, results),
                            daemon=True
                        )
                        running_threads[node.node_id] = t
                        t.start()
                    except Exception as e:
                        node.update_status(file_id, "failed", f"Ошибка конвертации входа: {str(e)}")

        for child in node.children:
            self._traverse_and_trigger(child, file_id, language, node_states, running_threads, results, parent_node=node)

    def _execute_node_thread(self, node, file_id, language, node_input, results):
        try:
            output_data = node.run(node_input, self.client)
            with self._results_lock:
                results[node.node_id] = output_data
        except Exception as e:
            error_msg = f"Ошибка выполнения ноды: {str(e)}"
            
            logger.error(
                "node_execution_failed",
                node_id=node.node_id,
                file_id=file_id,
                error=str(e),
                exc_info=True
            )
            
            metrics.node_failures.labels(node_id=node.node_id).inc()
            metrics.workflows_failed.inc()
            
            node.update_status(file_id, NodeStatus.FAILED, error_msg)

    def _start_queue_processor(self):
        """Запускает фоновый поток для обработки очереди воркфлоу"""
        def process_queue():
            logger.info("queue_processor_started", max_concurrent=self.max_concurrent_workflows)
            while True:
                try:
                    # Проверяем, можем ли запустить новый воркфлоу
                    with self._queue_lock:
                        active_count = len(self.active_workflows)
                    
                    if active_count < self.max_concurrent_workflows:
                        # Пытаемся взять воркфлоу из очереди (неблокирующий вызов)
                        try:
                            workflow_id, file_id, file_path, language = self._workflow_queue.get(timeout=1)
                            
                            logger.info(
                                "workflow_dequeued",
                                workflow_id=workflow_id,
                                file_id=file_id,
                                queue_size=self._workflow_queue.qsize()
                            )
                            
                            # Запускаем воркфлоу
                            with self._queue_lock:
                                self.active_workflows.add(workflow_id)
                            
                            logger.info(
                                "workflow_started",
                                workflow_id=workflow_id,
                                file_id=file_id,
                                active_count=active_count + 1,
                                max_concurrent=self.max_concurrent_workflows
                            )
                            
                            metrics.workflow_active_count.set(active_count + 1)
                            metrics.workflow_queue_size.set(self._workflow_queue.qsize())
                            
                            t = threading.Thread(
                                target=self._run_orchestrator,
                                args=(workflow_id, file_id, file_path, language),
                                daemon=True
                            )
                            t.start()
                            
                        except Empty:
                            # Очередь пуста, ждём
                            pass
                        except Exception as e:
                            logger.error(
                                "queue_get_error",
                                error=str(e),
                                error_type=type(e).__name__,
                                exc_info=True
                            )
                            print(f"ERROR:  Error getting workflow from queue: {e}", file=__import__('sys').stderr)
                            import traceback
                            traceback.print_exc()
                    else:
                        # Достигнут лимит, ждём
                        logger.debug("queue_processor_waiting", active_count=active_count, max_concurrent=self.max_concurrent_workflows)
                        time.sleep(1)
                        
                except Exception as e:
                    logger.error(
                        "queue_processor_error",
                        error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True
                    )
                    print(f"ERROR:  Queue processor error: {e}", file=__import__('sys').stderr)
                    import traceback
                    traceback.print_exc()
                    time.sleep(1)
        
        self._queue_processor_thread = threading.Thread(target=process_queue, daemon=True)
        self._queue_processor_thread.start()
        
        logger.info(
            "queue_processor_thread_started",
            max_concurrent=self.max_concurrent_workflows
        )

    def resume_interrupted_workflows(self):
        """Восстанавливает прерванные воркфлоу после перезапуска приложения"""
        interrupted = self._repository.get_interrupted_files()

        for file_info in interrupted:
            file_id = file_info.id
            file_path = file_info.original_path

            if not os.path.exists(file_path):
                logger.warning(
                    "workflow_resume_skipped",
                    file_id=file_id,
                    filename=file_info.filename,
                    reason="file_not_found"
                )
                continue

            logger.info(
                "workflow_resuming",
                file_id=file_id,
                filename=file_info.filename
            )

            self.start_orchestration(
                workflow_id=file_id,
                file_id=file_id,
                file_path=file_path,
                language=file_info.language
            )
