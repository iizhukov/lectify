import os
import sys
import time
import pathlib
import threading

from src.db.repository import DBRepository
from src.db.models import NodeStatus
from src.workflows.registry import WORKFLOW_REGISTRY
from src.workflows.converter import get_converter
from src.nodes.media_converter.models import MediaConverterInput


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
        self._repository = DBRepository()
        self.workflow = WORKFLOW_REGISTRY["lecture_workflow"]
        self._initialized = True

    def init_workflow(self, file_id: str, filename: str, language: str):
        self._repository.create_file(file_id, filename, language)

        self._repository.create_workflow(
            workflow_id=file_id, # Используем ID файла как ID этого инстанса воркфлоу
            file_id=file_id,
            name=self.workflow.name
        )

        nodes_data = [
            {"node_id": node.node_id, "node_name": node.name} 
            for node in self.workflow.all_nodes
        ]

        self._repository.create_workflow_nodes(file_id, nodes_data)

    def start_orchestration(self, file_id: str, file_path: str, language: str):
        t = threading.Thread(target=self._run_orchestrator, args=(file_id, file_path, language), daemon=True)
        t.start()

    def resume_interrupted_workflows(self):
        interrupted = self._repository.get_interrupted_files()
        for file_info in interrupted:
            fid = file_info["id"]
            filename = file_info["filename"]
            language = file_info["language"]
            
            possible_path = None
            for item in pathlib.Path("data").glob(f"*{filename}"):
                if fid in item.name:
                    possible_path = str(item)
                    break

            if possible_path and os.path.exists(possible_path):
                print(f"🔄 Восстановление работы воркфлоу для {filename} ({fid})")
                self.start_orchestration(fid, possible_path, language)

    def _run_orchestrator(self, file_id: str, file_path: str, language: str):
        results = {
            "root_input": MediaConverterInput(file_id=file_id, file_path=file_path)
        }
        running_threads = {}
        
        self._repository.update_workflow(file_id, NodeStatus.RUNNING)
        
        while True:
            file_details = self._repository.get_file_details(file_id)
            if not file_details:
                break
                
            node_states = {node.node_id: node.status for node in file_details.nodes}
            
            all_done = True
            for nid, status in node_states.items():
                if status not in ["completed", "failed"]:
                    all_done = False
                    break

            if all_done:
                overall_status = NodeStatus.COMPLETED
                if any(s == "failed" for s in node_states.values()):
                    overall_status = NodeStatus.FAILED
                
                final_path = None
                pdf_node = next((n for n in file_details.nodes if n.node_id == "latex_to_pdf"), None)
                md_node = next((n for n in file_details.nodes if n.node_id == "text_to_md"), None)

                if pdf_node and pdf_node.artifact_path:
                    final_path = pdf_node.artifact_path
                elif md_node and md_node.artifact_path:
                    final_path = md_node.artifact_path
                
                self._repository.update_workflow(file_id, overall_status, final_artifact_path=final_path)
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

    def _traverse_and_trigger(self, node, file_id, language, node_states, running_threads, results, parent_node=None):
        current_status = node_states.get(node.node_id)
        
        if current_status == "completed" and node.node_id not in results:
            file_details = self._repository.get_file_details(file_id)
            db_node = next((n for n in file_details.nodes if n.node_id == node.node_id), None)

            if db_node and db_node.artifact_path:
                path_field_name = list(node.output_model.model_fields.keys())[1]
                kwargs = {"file_id": file_id, path_field_name: db_node.artifact_path}
                results[node.node_id] = node.output_model(**kwargs)

        if current_status == "pending" and node.node_id not in running_threads:
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
            results[node.node_id] = output_data
        except Exception as e:
            pass
